"""
TradingView API - Python Implementation
A library to interact with TradingView's websocket API for real-time market data and indicators.

The module now includes helpers for fetching PineScript metadata (via
:getfunc:`get_indicator`) and performing a TradingView login.  Combined with
:class:`PineIndicator.set_option`, it is possible to load an authenticated
user's private/published script and run it with custom inputs.  Once the
indicator object has been obtained and configured it may be passed directly
into :pyclass:`ChartSession` to create a study or strategy.

For users who manage their own Pine scripts the :class:`PineFacadeClient`
provides asynchronous methods to compile, create, update, delete and list
scripts via TradingView's ``pine-facade`` HTTP API.  This makes it easier to
fetch a remote source, push new versions, and then immediately execute the
script with custom inputs on any market symbol.
"""

import asyncio
import json
import re
import base64
import zipfile
import io
import os
import math
import random
import string
from typing import Dict, List, Any, Optional, Callable, Literal, Union
from datetime import datetime
import aiohttp
import websockets


# ============================================================================
# UTILS
# ============================================================================

def gen_session_id(prefix: str = "xs") -> str:
    """Generate a random session ID."""
    chars = string.ascii_letters + string.digits
    random_str = ''.join(random.choice(chars) for _ in range(12))
    return f"{prefix}_{random_str}"


def _extract_cookie_value(input_str: str = "", cookie_name: str = "") -> str:
    """Extract cookie value from cookie string or return raw value.
    
    Matches JS extractCookieValue implementation.
    """
    if not input_str:
        return ""
    
    # If it looks like a full cookie string, extract the value
    if f"{cookie_name}=" in input_str:
        import re
        match = re.search(rf"{cookie_name}=([^;\s]+)", input_str)
        if match:
            return match.group(1)
        return ""
    
    # Return raw value
    return str(input_str)


def gen_auth_cookies(session_id: str = "", signature: str = "") -> str:
    """Generate authentication cookies string.
    
    Matches the JS implementation: supports extracting cookie values from
    full cookie strings, otherwise builds from raw SESSION/SIGNATURE values.
    """
    sid = _extract_cookie_value(session_id, "sessionid")
    sig = _extract_cookie_value(signature, "sessionid_sign")
    
    if not sid:
        return ""
    if not sig:
        return f"sessionid={sid}"
    return f"sessionid={sid};sessionid_sign={sig}"


# ============================================================================
# HTTP / PINE helpers
# ============================================================================

async def get_indicator(
    id: str,
    version: str = "last",
    session: str = "",
    signature: str = "",
) -> PineIndicator:
    """Fetch an indicator (builtin or user script) from TradingView.

    This mirrors the behaviour of :meth:`tvjs.miscRequests.getIndicator` and
    is the mechanism needed to obtain the metadata that describes a
    PineScript.  The returned object can be supplied directly to
    :meth:`ChartSession.create_study` or manipulated with
    :meth:`PineIndicator.set_option` before creating the study.

    If ``session``/``signature`` cookies are supplied they will be added to
    the request; this is *required* for private or invite‑only scripts.
    The ``id`` argument should be the full Pine ID (e.g. ``"USER;..."`` or
    ``"PUB;..."`` or ``"STD;EMA"``).
    """
    # the endpoint expects spaces/percent signs to be encoded as %25
    indic_id = re.sub(r"[ %]", "%25", id)
    url = f"https://pine-facade.tradingview.com/pine-facade/translate/{indic_id}/{version}"

    headers = {"Origin": "https://www.tradingview.com"}
    if session or signature:
        headers["Cookie"] = gen_auth_cookies(session, signature)

    async with aiohttp.ClientSession() as http:
        async with http.get(url, headers=headers) as resp:
            # the facade often returns ``text/plain`` despite containing JSON
            txt = await resp.text()
            try:
                data = json.loads(txt)
            except Exception as e:
                raise ValueError(f"unexpected response from translate endpoint: {e}\n{text[:200]}")

    if not data.get("success") or not data.get("result", {}).get("metaInfo", {}).get("inputs"):
        raise ValueError(f"Inexistent or unsupported indicator: {data.get('reason')}")

    meta = data["result"]["metaInfo"]
    inputs: Dict[str, Any] = {}
    for inp in meta.get("inputs", []):
        if inp.get("id") in ("text", "pineId", "pineVersion"):
            continue

        inline_name = re.sub(r"[^a-zA-Z0-9_]", "", inp.get("name", "").replace(" ", "_"))
        inputs[inp["id"]] = {
            "name": inp.get("name"),
            "inline": inp.get("inline") or inline_name,
            "internalID": inp.get("internalID", inline_name),
            "tooltip": inp.get("tooltip"),
            "type": inp.get("type"),
            "value": inp.get("defval"),
            "isHidden": bool(inp.get("isHidden")),
            "isFake": bool(inp.get("isFake")),
        }
        if inp.get("options"):
            inputs[inp["id"]]["options"] = inp.get("options")

    # plot names: some may collide, follow same dedup logic as tvjs
    plots: Dict[str, str] = {}
    for pid, style in (meta.get("styles") or {}).items():
        title = re.sub(r"[^a-zA-Z0-9_]", "", style.get("title", "").replace(" ", "_"))
        if title in plots.values():
            i = 2
            base = title
            while f"{base}_{i}" in plots.values():
                i += 1
            title = f"{base}_{i}"
        plots[pid] = title

    for p in meta.get("plots", []):
        if not p.get("target"):
            continue
        parent = plots.get(p.get("target")) or p.get("target")
        plots[p["id"]] = f"{parent}_{p.get('type')}"

    options = {
        "pineId": meta.get("scriptIdPart") or indic_id,
        "pineVersion": meta.get("pine", {}).get("version", version),
        "description": meta.get("description"),
        "shortDescription": meta.get("shortDescription"),
        "inputs": inputs,
        "plots": plots,
        "script": data.get("result", {}).get("ilTemplate", ""),
    }
    return PineIndicator(options)


async def login_user(
    username: str,
    password: str,
    remember: bool = True,
    UA: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
) -> Dict[str, Any]:
    """Authenticate against TradingView and return the session info.

    The returned dictionary contains ``session`` and ``signature`` keys which
    can subsequently be passed to :func:`get_indicator` for private scripts.
    This is a direct port of the Javascript ``loginUser`` helper.
    
    Note: TradingView may block login attempts from certain regions or with
    automated patterns. If login fails, consider using pre-obtained SESSION/
    SIGNATURE cookies from a manual browser login.
    """
    async with aiohttp.ClientSession() as http:
        # Step 1: Get the login page to receive CSRF cookie
        login_page_url = "https://www.tradingview.com/"
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        async with http.get(login_page_url, headers=headers) as resp:
            # Get the CSRF token from cookies
            csrf_token = resp.cookies.get("csrftoken").value if resp.cookies.get("csrftoken") else ""

        # Step 2: Submit login credentials
        payload = {
            "username": username,
            "password": password,
        }
        if remember:
            payload["remember"] = "on"

        headers = {
            "referer": "https://www.tradingview.com/",
            "origin": "https://www.tradingview.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": UA,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.5",
            "X-CSRFToken": csrf_token,
        }

        async with http.post(
            "https://www.tradingview.com/accounts/signin/",
            data=payload,
            headers=headers,
        ) as resp:
            text = await resp.text()
            cookies = resp.cookies

            # extract cookies for session and signature
            session = cookies.get("sessionid").value if cookies.get("sessionid") else ""
            signature = cookies.get("sessionid_sign").value if cookies.get("sessionid_sign") else ""

            if not session:
                # Try to get more info about the failure
                raise ValueError(f"login failed, no session cookie returned. Response: {text[:500]}")

        return {"session": session, "signature": signature}


# ============================================================================
# MISC REQUESTS (search, get_user, etc.)
# ============================================================================

async def get_user(session: str, signature: str = "", location: str = "https://www.tradingview.com/", _redirect_depth: int = 0) -> Dict[str, Any]:
    """Get user from sessionid cookie.
    
    Matches JS getUser implementation with redirect handling.
    """
    max_redirects = 10
    if _redirect_depth > max_redirects:
        raise Exception("Too many redirects while fetching TradingView user")
    
    headers = {
        "Cookie": gen_auth_cookies(session, signature),
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    async with aiohttp.ClientSession() as http:
        async with http.get(location, headers=headers, allow_redirects=False) as resp:
            data = await resp.text()
            
            if "auth_token" in data:
                # Parse user data from HTML
                import re
                
                def parse_int_safe(s, default=0):
                    try:
                        return int(s) if s else default
                    except (ValueError, TypeError):
                        return default
                
                def parse_float_safe(s, default=0):
                    try:
                        return float(s) if s else default
                    except (ValueError, TypeError):
                        return default
                
                id_match = re.search(r'"id":([0-9]{1,10}),', data)
                username_match = re.search(r'"username":"(.*?)"', data)
                first_name_match = re.search(r'"first_name":"(.*?)"', data)
                last_name_match = re.search(r'"last_name":"(.*?)"', data)
                reputation_match = re.search(r'"reputation":(.*?),', data)
                following_match = re.search(r',"following":([0-9]*?),', data)
                followers_match = re.search(r',"followers":([0-9]*?),', data)
                session_hash_match = re.search(r'"session_hash":"(.*?)"', data)
                private_channel_match = re.search(r'"private_channel":"(.*?)"', data)
                auth_token_match = re.search(r'"auth_token":"(.*?)"', data)
                date_joined_match = re.search(r'"date_joined":"(.*?)"', data)
                
                return {
                    "id": parse_int_safe(id_match.group(1) if id_match else None),
                    "username": username_match.group(1) if username_match else "",
                    "firstName": first_name_match.group(1) if first_name_match else "",
                    "lastName": last_name_match.group(1) if last_name_match else "",
                    "reputation": parse_float_safe(reputation_match.group(1) if reputation_match else None),
                    "following": parse_int_safe(following_match.group(1) if following_match else None),
                    "followers": parse_int_safe(followers_match.group(1) if followers_match else None),
                    "session": session,
                    "signature": signature,
                    "sessionHash": session_hash_match.group(1) if session_hash_match else "",
                    "privateChannel": private_channel_match.group(1) if private_channel_match else "",
                    "authToken": auth_token_match.group(1) if auth_token_match else "",
                    "joinDate": datetime.fromisoformat(date_joined_match.group(1).replace('Z', '+00:00')) if date_joined_match else datetime.now(),
                }
            
            # Handle redirect
            if resp.status in (301, 302, 307, 308) and resp.headers.get("location"):
                new_location = resp.headers["location"]
                if new_location != location:
                    return await get_user(session, signature, new_location, _redirect_depth + 1)
    
    raise AuthenticationError("Wrong or expired sessionid/signature")


async def search_market_v3(search: str, filter_type: str = "", offset: int = 0) -> List[Dict[str, Any]]:
    """Search for markets using v3 API.
    
    Matches JS searchMarketV3 implementation.
    """
    splitted_search = search.upper().replace(" ", "+").split(":")
    
    params = {
        "text": splitted_search[-1],
        "search_type": filter_type if filter_type else None,
        "start": offset,
    }
    
    if len(splitted_search) == 2:
        params["exchange"] = splitted_search[0]
    
    # Remove None values
    params = {k: v for k, v in params.items() if v is not None}
    
    headers = {
        "Origin": "https://www.tradingview.com",
    }
    
    async with aiohttp.ClientSession() as http:
        async with http.get(
            "https://symbol-search.tradingview.com/symbol_search/v3",
            params=params,
            headers=headers
        ) as resp:
            data = await resp.json()
    
    results = []
    for s in data.get("symbols", []):
        exchange = s.get("exchange", "").split(" ")[0]
        prefix = s.get("prefix")
        symbol = s.get("symbol", "")
        id_str = f"{prefix}:{symbol}" if prefix else f"{exchange.upper()}:{symbol}"
        
        async def get_ta_func(id_val):
            return await get_ta(id_val)
        
        results.append({
            "id": id_str,
            "exchange": exchange,
            "fullExchange": s.get("exchange", ""),
            "symbol": symbol,
            "description": s.get("description", ""),
            "type": s.get("type", ""),
            "getTA": lambda id_val=id_str: get_ta_func(id_val),
        })
    
    return results


_built_in_indic_list = []

async def search_indicator(search: str = "") -> List[Dict[str, Any]]:
    """Search for indicators.
    
    Matches JS searchIndicator implementation.
    """
    global _built_in_indic_list
    
    # Load built-in indicators if not already loaded
    if not _built_in_indic_list:
        for type_filter in ["standard", "candlestick", "fundamental"]:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://pine-facade.tradingview.com/pine-facade/list",
                    params={"filter": type_filter}
                ) as resp:
                    text = await resp.text()
                    try:
                        data = json.loads(text)
                        if isinstance(data, list):
                            _built_in_indic_list.extend(data)
                    except json.JSONDecodeError:
                        pass
    
    async with aiohttp.ClientSession() as http:
        async with http.get(
            "https://www.tradingview.com/pubscripts-suggest-json",
            params={"search": search.replace(" ", "%20")}
        ) as resp:
            data = await resp.json()
    
    def normalize_string(s: str = "") -> str:
        return re.sub(r'[^A-Z]', '', s.upper())
    
    search_norm = normalize_string(search)
    
    # Filter built-in indicators
    def matches_search(ind):
        name_norm = normalize_string(ind.get("scriptName", ""))
        desc_norm = normalize_string(ind.get("extra", {}).get("shortDescription", ""))
        return search_norm in name_norm or search_norm in desc_norm
    
    # Map built-in indicators
    def map_built_in(ind):
        script_id = ind.get("scriptIdPart", "")
        version = ind.get("version", "last")
        
        async def get_ind():
            return await get_indicator(script_id, version)
        
        return {
            "id": script_id,
            "version": version,
            "name": ind.get("scriptName", ""),
            "author": {"id": ind.get("userId"), "username": "@TRADINGVIEW@"},
            "image": "",
            "access": "closed_source",
            "source": "",
            "type": ind.get("extra", {}).get("kind", "study"),
            "get": get_ind,
        }
    
    # Map user indicators
    def map_user(ind):
        script_id = ind.get("scriptIdPart", "")
        version = ind.get("version", "last")
        
        async def get_ind():
            return await get_indicator(script_id, version)
        
        access_map = ["open_source", "closed_source", "invite_only"]
        access_idx = ind.get("access", 4) - 1
        
        return {
            "id": script_id,
            "version": version,
            "name": ind.get("scriptName", ""),
            "author": {
                "id": ind.get("author", {}).get("id"),
                "username": ind.get("author", {}).get("username", "")
            },
            "image": ind.get("imageUrl", ""),
            "access": access_map[access_idx] if 0 <= access_idx < 3 else "other",
            "source": ind.get("scriptSource", ""),
            "type": ind.get("extra", {}).get("kind", "study"),
            "get": get_ind,
        }
    
    built_in_filtered = [map_built_in(ind) for ind in _built_in_indic_list if matches_search(ind)]
    user_results = [map_user(ind) for ind in data.get("results", [])]
    
    return built_in_filtered + user_results


async def get_private_indicators(session: str, signature: str = "") -> List[Dict[str, Any]]:
    """Get user's private indicators from sessionid cookie.
    
    Matches JS getPrivateIndicators implementation.
    """
    headers = {
        "Cookie": gen_auth_cookies(session, signature),
    }
    
    async with aiohttp.ClientSession() as http:
        async with http.get(
            "https://pine-facade.tradingview.com/pine-facade/list",
            params={"filter": "saved"},
            headers=headers
        ) as resp:
            text = await resp.text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return []
    
    if not isinstance(data, list):
        return []
    
    def map_private(ind):
        script_id = ind.get("scriptIdPart", "")
        version = ind.get("version", "last")
        
        async def get_ind():
            return await get_indicator(script_id, version, session, signature)
        
        return {
            "id": script_id,
            "version": version,
            "name": ind.get("scriptName", ""),
            "author": {"id": -1, "username": "@ME@"},
            "image": ind.get("imageUrl", ""),
            "access": "private",
            "source": ind.get("scriptSource", ""),
            "type": ind.get("extra", {}).get("kind", "study"),
            "get": get_ind,
        }
    
    return [map_private(ind) for ind in data]


async def get_ta(id: str) -> Dict[str, Any]:
    """Get technical analysis for a symbol.
    
    Matches JS getTA implementation.
    """
    indicators = ["Recommend.Other", "Recommend.All", "Recommend.MA"]
    
    cols = []
    for t in ["1", "5", "15", "60", "240", "1D", "1W", "1M"]:
        for i in indicators:
            cols.append(i if t == "1D" else f"{i}|{t}")
    
    async with aiohttp.ClientSession() as http:
        async with http.post(
            "https://scanner.tradingview.com/global/scan",
            json={
                "symbols": {"tickers": [id]},
                "columns": cols,
            }
        ) as resp:
            data = await resp.json()
    
    if not data.get("data") or not data["data"][0]:
        return {}
    
    advice = {}
    values = data["data"][0].get("d", [])
    
    for i, val in enumerate(values):
        col = cols[i]
        parts = col.split("|")
        name = parts[0]
        period = parts[1] if len(parts) > 1 else "1D"
        
        if period not in advice:
            advice[period] = {}
        
        advice[period][name.split(".")[-1]] = round(val * 1000) / 500
    
    return advice


# helpers used by the script manager

def normalize_pine_id(raw: str) -> str:
    """Canonicalize a Pine ID string (replace encoded semicolons)."""
    return str(raw or "").strip().replace("%3B", ";")


def normalize_timeframe(tf: str) -> str:
    """Convert user-friendly timeframes ("5m","1h", etc.) to
    TradingView resolution strings.

    - Numeric strings and D/W/M are passed through unchanged.
    - "Xm" becomes the number of minutes X.
    - "Xh" becomes X*60.
    """
    t = str(tf or "").strip()
    if not t:
        return "5"
    if t.isdigit() or t in ("D", "W", "M"):
        return t
    m = re.match(r"^(\d+)\s*m$", t, re.IGNORECASE)
    if m:
        return m.group(1)
    h = re.match(r"^(\d+)\s*h$", t, re.IGNORECASE)
    if h:
        return str(int(h.group(1)) * 60)
    return t


def looks_like_pine_id(s: str) -> bool:
    """Check if string looks like a valid Pine ID."""
    import re
    return bool(re.match(r"^\s*(USER|PUB|STD|INDIC);", str(s or ""), re.IGNORECASE))


def extract_pine_id_from_response(obj: Any) -> Optional[str]:
    """Extract Pine ID from various response formats.
    
    Matches JS extractPineIdFromResponse implementation.
    Handles:
    - String responses with embedded pineId
    - Object responses with id/pineId/scriptIdPart fields
    - Nested result.metaInfo.scriptIdPart
    """
    if not obj:
        return None
    
    if isinstance(obj, str):
        s = normalize_pine_id(obj)
        if s.startswith('{') or s.startswith('['):
            try:
                return extract_pine_id_from_response(json.loads(s))
            except Exception:
                pass
        # Look for pineId pattern in string
        match = re.search(r'\b(?:USER|PUB|STD|INDIC);[^\s"\'<>]+', s, re.IGNORECASE)
        return normalize_pine_id(match.group(0)) if match else None
    
    if isinstance(obj, list):
        for item in obj:
            found = extract_pine_id_from_response(item)
            if found:
                return found
        return None
    
    if isinstance(obj, dict):
        # Check common keys
        for key in ['id', 'pineId', 'pine_id', 'scriptIdPart', 'script_id', 'scriptId', 'result', 'data']:
            if key in obj:
                found = extract_pine_id_from_response(obj[key])
                if found:
                    return found
        
        # Check result.metaInfo.scriptIdPart
        if 'result' in obj and obj['result'] and isinstance(obj['result'], dict):
            meta_info = obj['result'].get('metaInfo', {})
            if meta_info and meta_info.get('scriptIdPart'):
                part = meta_info['scriptIdPart']
                if isinstance(part, str):
                    if ';' in part:
                        return normalize_pine_id(part)
                    return normalize_pine_id(f"USER;{part}")
    
    return None


def _parse_save_response(resp: Any) -> Dict[str, Any]:
    """Normalize the response from save/compile endpoints for easier access.

    Returns a dictionary with keys: `pineId`, `version`, `success`, `reason`,
    `errors` and `raw` (original payload parsed as JSON if possible).
    
    Matches JS parseSaveResponse implementation.
    """
    data = resp
    if isinstance(resp, str):
        try:
            data = json.loads(resp)
        except Exception:
            data = {"raw": resp}
    
    pine_id = extract_pine_id_from_response(data)
    
    version = None
    if isinstance(data, dict):
        version = (
            data.get("version") or
            data.get("result", {}).get("version") or
            data.get("result", {}).get("metaInfo", {}).get("version")
        )
    
    success = (
        isinstance(data.get("success"), bool) and data["success"] or
        bool(data.get("result"))
    )
    
    reason = data.get("reason")
    errors = (
        data.get("result", {}).get("errors")
        if isinstance(data.get("result"), dict) else None
    )
    
    return {
        "pineId": pine_id,
        "version": version,
        "success": success,
        "reason": reason,
        "errors": errors,
        "raw": data
    }


class PineFacadeClient:
    """Light wrapper around the TradingView "pine-facade" HTTP API.
    
    Provides convenience methods for compiling, saving, fetching and listing
    Pine scripts. Uses :mod:`aiohttp` for async requests and accepts the same
    ``session``/``signature`` cookies as the websocket client.
    
    Matches the JS PineClient implementation with:
    - Proper version resolution (latest version detection)
    - Better error messages for authentication failures
    - Support for both text/plain and JSON responses
    """

    def __init__(
        self,
        session_id: str = "",
        signature: str = "",
        base_url: str = "https://pine-facade.tradingview.com/pine-facade",
        timeout: float = 120_000,
        user_name: str = "",
    ):
        self.session_id = session_id
        self.signature = signature
        self.base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout / 1000)
        self._http: Optional[aiohttp.ClientSession] = None
        self.user_name = user_name

    def _headers(self) -> Dict[str, str]:
        hdrs = {
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
        }
        if self.session_id or self.signature:
            hdrs["Cookie"] = gen_auth_cookies(self.session_id, self.signature)
        return hdrs

    async def _http_session(self) -> aiohttp.ClientSession:
        if not self._http or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=self._timeout)
        return self._http

    async def close(self):
        if self._http and not self._http.closed:
            await self._http.close()

    async def compile(self, source: str, user: str = "") -> Dict[str, Any]:
        """Compile a Pine script without saving. ``user`` is optional but may be
        required by some endpoints. Returns the raw response parsed as JSON-like
        dictionary.  Some endpoints return ``text/plain`` with JSON inside, so the
        result is coerced accordingly.
        """
        url = f"{self.base_url}/translate_light"
        params = {"v": "3"}
        if user:
            params["user_name"] = user
        form = aiohttp.FormData()
        form.add_field("source", source)
        sess = await self._http_session()
        async with sess.post(url, params=params, data=form, headers=self._headers()) as resp:
            text = await resp.text()
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text}

    async def save_new(self, source: str, name: str, user: str = "") -> Dict[str, Any]:
        """Create a new script on TradingView. Requires authentication.
        ``name`` is the publication name. Returns raw response.
        """
        if not user:
            raise ValueError("save_new requires a user name (TV_USER)")
        url = f"{self.base_url}/save/new"
        params = {"name": name, "user_name": user, "allow_overwrite": "true"}
        form = aiohttp.FormData()
        form.add_field("source", source)
        sess = await self._http_session()
        async with sess.post(url, params=params, data=form, headers=self._headers()) as resp:
            text = await resp.text()
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text}

    async def save_next(self, pine_id: str, source: str, user: str = "") -> Dict[str, Any]:
        """Push the next version of an existing script. Requires authentication.
        """
        if not user:
            raise ValueError("save_next requires a user name (TV_USER)")
        pine = normalize_pine_id(pine_id)
        url = f"{self.base_url}/save/next/{aiohttp.helpers.quote(pine)}"
        params = {"user_name": user}
        form = aiohttp.FormData()
        form.add_field("source", source)
        sess = await self._http_session()
        async with sess.post(url, params=params, data=form, headers=self._headers()) as resp:
            text = await resp.text()
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text}

    async def delete(self, pine_id: str, user: str = "") -> Any:
        """Delete a remote saved script. Requires authentication."""
        if not user:
            raise ValueError("delete requires a user name (TV_USER)")
        pine = normalize_pine_id(pine_id)
        url = f"{self.base_url}/delete/{aiohttp.helpers.quote(pine)}"
        params = {"user_name": user}
        sess = await self._http_session()
        async with sess.post(url, params=params, headers=self._headers()) as resp:
            try:
                return await resp.json()
            except Exception:
                return await resp.text()

    async def list_saved(self) -> Any:
        """Return the list of saved scripts the authenticated user has access to."""
        url = f"{self.base_url}/list"
        params = {"filter": "saved"}
        sess = await self._http_session()
        async with sess.get(url, params=params, headers=self._headers()) as resp:
            try:
                return await resp.json()
            except Exception:
                return await resp.text()

    async def fetch(self, pine_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Fetch the raw source and metadata for a script.

        Returns ``{source: str, meta: dict}`` like the JS PineClient.get().
        """
        pine = normalize_pine_id(pine_id)
        # try resolve version logic similar to JS version.
        target = version or 'last'
        url = f"{self.base_url}/translate/{aiohttp.helpers.quote(pine)}/{aiohttp.helpers.quote(target)}"
        sess = await self._http_session()
        async with sess.get(url, headers=self._headers()) as resp:
            payload = await resp.text()
            try:
                data = json.loads(payload)
            except Exception:
                data = payload
            return self._parse_fetch_response(data)

    async def get(self, pine_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Get script source with version resolution.
        
        Matches JS PineClient.get() with:
        - Automatic latest version resolution if version is None or '-1'
        - Fallback to version list endpoint if direct fetch fails
        - Returns {source: str, meta: dict}
        """
        pine = normalize_pine_id(pine_id)
        resolved_version = version if version and version != '-1' else None
        
        # Try to resolve latest version if not specified
        if not resolved_version:
            resolved_version = await self._resolve_latest_version(pine)
        
        target_version = resolved_version or 'last'
        
        # Try direct get first
        if resolved_version:
            result = await self._try_get_version(pine, resolved_version)
            if result and result.get('source'):
                return result
        
        # Fallback to translate endpoint
        return await self.fetch(pine_id, target_version)

    async def _resolve_latest_version(self, pine_id: str) -> Optional[str]:
        """Resolve the latest version of a script.
        
        Matches JS _resolveLatestVersion implementation.
        Returns the highest version string or None if unable to resolve.
        """
        try:
            url = f"{self.base_url}/versions/{aiohttp.helpers.quote(pine_id)}"
            sess = await self._http_session()
            async with sess.get(url, headers=self._headers()) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                versions = self._normalize_version_entries(data)
                candidates = [
                    self._extract_version_from_entry(e)
                    for e in versions
                ]
                candidates = [v for v in candidates if v]
                return self._choose_highest_version(candidates)
        except Exception:
            return None

    def _normalize_version_entries(self, data: Any) -> List[Any]:
        """Normalize version entries from response."""
        if not data:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if isinstance(data.get('versions'), list):
                return data['versions']
            if isinstance(data.get('result', {}).get('versions'), list):
                return data['result']['versions']
            if isinstance(data.get('data'), list):
                return data['data']
        return []

    def _extract_version_from_entry(self, entry: Any) -> Optional[str]:
        """Extract version string from a version entry."""
        if not entry:
            return None
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return (
                entry.get('version') or
                entry.get('result', {}).get('version') or
                entry.get('metaInfo', {}).get('version') or
                entry.get('scriptVersion') or
                entry.get('sourceVersion')
            )
        return None

    def _choose_highest_version(self, versions: List[str]) -> Optional[str]:
        """Choose the highest version from a list.
        
        Matches JS compareVersionStrings implementation.
        """
        best = None
        for candidate in versions:
            if not candidate:
                continue
            if not best or self._compare_versions(candidate, best) > 0:
                best = candidate
        return best

    def _compare_versions(self, a: str, b: str) -> int:
        """Compare two version strings.
        
        Returns:
            1 if a > b, -1 if a < b, 0 if equal
        """
        def normalize(v):
            return str(v or '').strip()
        
        def to_parts(value):
            return [
                int(p) if p.isdigit() else 0
                for p in normalize(value).split('.')
            ]
        
        a_parts = to_parts(a)
        b_parts = to_parts(b)
        max_len = max(len(a_parts), len(b_parts))
        
        for i in range(max_len):
            a_val = a_parts[i] if i < len(a_parts) else 0
            b_val = b_parts[i] if i < len(b_parts) else 0
            if a_val > b_val:
                return 1
            if a_val < b_val:
                return -1
        return 0

    async def _try_get_version(self, pine_id: str, version: str) -> Optional[Dict[str, Any]]:
        """Try to get a specific version of a script.
        
        Matches JS _tryGetVersion implementation.
        """
        url = f"{self.base_url}/get/{aiohttp.helpers.quote(pine_id)}/{aiohttp.helpers.quote(version)}"
        sess = await self._http_session()
        async with sess.get(url, headers=self._headers()) as resp:
            if resp.status != 200:
                return None
            payload = await resp.text()
            try:
                data = json.loads(payload)
            except Exception:
                data = payload
            
            result = self._parse_fetch_response(data)
            if result.get('source'):
                return result
            
            # Check if meta has a different version
            meta = result.get('meta')
            if meta and meta.get('version') and meta['version'] != version:
                url = f"{self.base_url}/get/{aiohttp.helpers.quote(pine_id)}/{aiohttp.helpers.quote(meta['version'])}"
                async with sess.get(url, headers=self._headers()) as resp2:
                    if resp2.status == 200:
                        payload2 = await resp2.text()
                        try:
                            data2 = json.loads(payload2)
                        except Exception:
                            data2 = payload2
                        result2 = self._parse_fetch_response(data2)
                        if result2.get('source'):
                            return result2
        return None

    def _parse_fetch_response(self, data: Any) -> Dict[str, Any]:
        # simplified parsing of JS _parseResponse
        if isinstance(data, str):
            return {"source": data, "meta": None}
        if isinstance(data, dict):
            source = data.get("source") or data.get("scriptSource") or data.get("result", {}).get("scriptSource") or ''
            meta = None
            if data.get("metaInfo") or data.get("result", {}).get("metaInfo"):
                meta = data.get("metaInfo") or data.get("result", {}).get("metaInfo")
            return {"source": source, "meta": meta}
        return {"source": '', "meta": None}

# ============================================================================
# CONFIG
# ============================================================================

class _Config:
    """Configuration module for TradingView API."""
    
    def __init__(self):
        self._debug = False
    
    @property
    def debug(self) -> bool:
        return self._debug
    
    def set_debug(self, value: bool):
        """Set debug mode."""
        if not isinstance(value, bool):
            raise TypeError("Debug value must be a boolean")
        self._debug = value


_config = _Config()


def set_debug(value: bool):
    """Enable or disable debug logging."""
    _config.set_debug(value)


def is_debug_enabled() -> bool:
    """Check if debug mode is enabled."""
    return _config.debug


# ============================================================================
# ERRORS
# ============================================================================

class TradingViewAPIError(Exception):
    """Base error class for TradingView API errors."""
    
    def __init__(self, message: str, error_type: str = "unknown", details: Any = None):
        super().__init__(message)
        self.name = self.__class__.__name__
        self.type = error_type
        self.details = details


class ConnectionError(TradingViewAPIError):
    """Network/Connection related errors."""
    
    def __init__(self, message: str, details: Any = None):
        super().__init__(message, "connection", details)


class ProtocolError(TradingViewAPIError):
    """Protocol/WebSocket packet errors."""
    
    def __init__(self, message: str, details: Any = None):
        super().__init__(message, "protocol", details)


class ValidationError(TradingViewAPIError):
    """Input validation errors."""
    
    def __init__(self, message: str, field: str = None, details: Any = None):
        super().__init__(message, "validation", details)
        self.field = field


class AuthenticationError(TradingViewAPIError):
    """Authentication/Authorization errors."""
    
    def __init__(self, message: str, details: Any = None):
        super().__init__(message, "authentication", details)


class SymbolError(TradingViewAPIError):
    """Symbol/Market errors."""
    
    def __init__(self, message: str, symbol: str = None, details: Any = None):
        super().__init__(message, "symbol", details)
        self.symbol = symbol


class IndicatorError(TradingViewAPIError):
    """Indicator/Study errors."""
    
    def __init__(self, message: str, indicator_id: str = None, details: Any = None):
        super().__init__(message, "indicator", details)
        self.indicator_id = indicator_id


class SessionError(TradingViewAPIError):
    """Session management errors."""
    
    def __init__(self, message: str, details: Any = None):
        super().__init__(message, "session", details)


# ============================================================================
# PROTOCOL
# ============================================================================

class Protocol:
    """WebSocket protocol parser and formatter."""
    
    _cleaner_rgx = re.compile(r"~h~")
    _splitter_rgx = re.compile(r"~m~\d+~m~")
    
    @staticmethod
    def parse_ws_packet(data: str) -> List[Any]:
        """Parse websocket packet.
        
        Matches JS parseWSPacket implementation with proper error handling.
        """
        # Remove ~h~ prefix from packets (heartbeat messages)
        cleaned = Protocol._cleaner_rgx.sub("", data)
        parts = Protocol._splitter_rgx.split(cleaned)
        
        result = []
        for part in parts:
            if not part:
                continue
            try:
                result.append(json.loads(part))
            except json.JSONDecodeError as e:
                # Log warning but don't throw - allow other packets to process
                if is_debug_enabled():
                    print(f"ProtocolError: Failed to parse WebSocket chunk: {e}")
                    print(f"Chunk preview: {part[:200]}")
                # Might be a ping number
                try:
                    if part.isdigit():
                        result.append(int(part))
                except ValueError:
                    pass
        return result
    
    @staticmethod
    def format_ws_packet(packet: Any) -> str:
        """Format websocket packet."""
        msg = json.dumps(packet) if isinstance(packet, dict) else str(packet)
        return f"~m~{len(msg)}~m~{msg}"
    
    @staticmethod
    async def parse_compressed(data: str) -> Dict:
        """Parse compressed data.
        
        Matches JS parseCompressed implementation with proper error handling.
        """
        try:
            decoded = base64.b64decode(data)
            with zipfile.ZipFile(io.BytesIO(decoded)) as zip_file:
                # Some payloads use an empty filename, others may use an arbitrary name
                namelist = zip_file.namelist()
                empty_name = "" in namelist
                first_name = namelist[0] if namelist else None
                
                filename = "" if empty_name else first_name
                if filename is None:
                    raise ProtocolError("Compressed payload contained no files", {
                        "availableFiles": namelist
                    })
                
                content = zip_file.read(filename)
                return json.loads(content)
        except ProtocolError:
            raise
        except Exception as e:
            raise ProtocolError("Failed to parse compressed data", {
                "originalError": str(e),
                "dataLength": len(data) if data else 0
            })


# ============================================================================
# INDICATORS
# ============================================================================

class PineIndicator:
    """Pine Script indicator representation."""
    
    def __init__(self, options: Dict):
        self._options = options
        self._type = "Script@tv-scripting-101!"
    
    @property
    def pine_id(self) -> str:
        return self._options.get("pineId", "")
    
    @property
    def pine_version(self) -> str:
        return self._options.get("pineVersion", "")
    
    @property
    def description(self) -> str:
        return self._options.get("description", "")
    
    @property
    def short_description(self) -> str:
        return self._options.get("shortDescription", "")
    
    @property
    def inputs(self) -> Dict:
        return self._options.get("inputs", {})
    
    @property
    def plots(self) -> Dict:
        return self._options.get("plots", {})
    
    @property
    def script(self) -> str:
        return self._options.get("script", "")
    
    @property
    def type(self) -> str:
        return self._type
    
    def set_type(self, indicator_type: str = "Script@tv-scripting-101!"):
        """Set the indicator type.
        
        Can be 'Script@tv-scripting-101!' or 'StrategyScript@tv-scripting-101!'.
        """
        self._type = indicator_type
    
    def set_option(self, key: str, value: Any):
        """Set an indicator option.

        The key can be either the raw input identifier (``in_0``), the
        inline name or the internalID. Similar to the Javascript helper
        this method will perform a small amount of type checking and will
        refuse invalid values or values that are not one of the allowed
        options when the input declares a finite set.
        """
        # locate property name inside the inputs dictionary
        prop_id = ""
        
        if f"in_{key}" in self.inputs:
            prop_id = f"in_{key}"
        elif key in self.inputs:
            prop_id = key
        else:
            # Try to find by inline or internalID
            for input_id, input_data in self.inputs.items():
                if input_data.get("inline") == key or input_data.get("internalID") == key:
                    prop_id = input_id
                    break

        if not prop_id or prop_id not in self.inputs:
            raise ValueError(f"Input '{key}' not found")

        input_def = self.inputs[prop_id]

        # Simple type validation copied from tvjs implementation
        types = {
            "bool": "Boolean",
            "boolean": "Boolean",
            "integer": "Number",
            "int": "Number",
            "float": "Number",
            "text": "String",
            "string": "String",
        }
        
        expected_type = types.get(input_def.get("type"))
        if expected_type:
            actual_type = type(value).__name__
            type_valid = False
            if expected_type == "Boolean" and isinstance(value, bool):
                type_valid = True
            elif expected_type == "Number" and isinstance(value, (int, float)):
                type_valid = True
            elif expected_type == "String" and isinstance(value, str):
                type_valid = True
                
            if not type_valid:
                raise TypeError(f"Input '{input_def.get('name')}' ({prop_id}) must be a {expected_type}!")

        if "options" in input_def and value not in input_def["options"]:
            raise ValueError(
                f"Input '{input_def.get('name')}' ({prop_id}) must be one of these values: {input_def['options']}"
            )

        input_def["value"] = value


class BuiltInIndicator:
    """Built-in indicator representation.
    
    Matches the JS BuiltInIndicator implementation with all default values.
    """
    
    DEFAULT_VALUES = {
        "Volume@tv-basicstudies-241": {
            "length": 20,
            "col_prev_close": False,
        },
        "VbPFixed@tv-basicstudies-241": {
            "rowsLayout": "Number Of Rows",
            "rows": 24,
            "volume": "Up/Down",
            "vaVolume": 70,
            "subscribeRealtime": False,
            "first_bar_time": float('nan'),
            "last_bar_time": None,
            "extendToRight": False,
            "mapRightBoundaryToBarStartTime": True,
        },
        "VbPFixed@tv-basicstudies-241!": {
            "rowsLayout": "Number Of Rows",
            "rows": 24,
            "volume": "Up/Down",
            "vaVolume": 70,
            "subscribeRealtime": False,
            "first_bar_time": float('nan'),
            "last_bar_time": None,
        },
        "VbPFixed@tv-volumebyprice-53!": {
            "rowsLayout": "Number Of Rows",
            "rows": 24,
            "volume": "Up/Down",
            "vaVolume": 70,
            "subscribeRealtime": False,
            "first_bar_time": float('nan'),
            "last_bar_time": None,
        },
        "VbPSessions@tv-volumebyprice-53": {
            "rowsLayout": "Number Of Rows",
            "rows": 24,
            "volume": "Up/Down",
            "vaVolume": 70,
            "extendPocRight": False,
        },
        "VbPSessionsRough@tv-volumebyprice-53!": {
            "volume": "Up/Down",
            "vaVolume": 70,
        },
        "VbPSessionsDetailed@tv-volumebyprice-53!": {
            "volume": "Up/Down",
            "vaVolume": 70,
            "subscribeRealtime": False,
            "first_visible_bar_time": float('nan'),
            "last_visible_bar_time": None,
        },
        "VbPVisible@tv-volumebyprice-53": {
            "rowsLayout": "Number Of Rows",
            "rows": 24,
            "volume": "Up/Down",
            "vaVolume": 70,
            "subscribeRealtime": False,
            "first_visible_bar_time": float('nan'),
            "last_visible_bar_time": None,
        },
    }
    
    def __init__(self, indicator_type: str):
        if not indicator_type:
            raise ValueError(f"Wrong built-in indicator type '{indicator_type}'")
        
        self._type = indicator_type
        self._options = self.DEFAULT_VALUES.get(indicator_type, {}).copy()
        
        # Set default for last_bar_time if it's None
        if self._options.get("last_bar_time") is None:
            self._options["last_bar_time"] = int(datetime.now().timestamp() * 1000)
        if self._options.get("last_visible_bar_time") is None:
            self._options["last_visible_bar_time"] = int(datetime.now().timestamp() * 1000)
    
    @property
    def type(self) -> str:
        return self._type
    
    @property
    def options(self) -> Dict:
        return self._options
    
    def set_option(self, key: str, value: Any, force: bool = False):
        """Set an option.
        
        Args:
            key: The option name
            value: The new value
            force: If True, ignore type and key verifications
        """
        if force:
            self._options[key] = value
            return
        
        # Check if key is valid for this indicator type
        defaults = self.DEFAULT_VALUES.get(self._type, {})
        if key in defaults:
            required_type = type(defaults[key])
            if required_type is float and isinstance(value, int):
                value = float(value)
            if required_type != type(value) and not (required_type is float and isinstance(value, int)):
                if not (isinstance(defaults[key], float) and isinstance(value, float) and math.isnan(value)):
                    raise TypeError(f"Wrong '{key}' value type '{type(value).__name__}' (must be '{required_type.__name__}')")
        elif defaults:
            raise ValueError(f"Option '{key}' is denied with '{self._type}' indicator")
        
        self._options[key] = value


# ============================================================================
# CHART STUDY
# ============================================================================

def _parse_trades(trades: List) -> List[Dict]:
    """Parse trades from strategy report.
    
    Matches JS parseTrades implementation.
    """
    result = []
    for trade in reversed(trades):
        result.append({
            "entry": {
                "name": trade.get("e", {}).get("c", ""),
                "type": "short" if trade.get("e", {}).get("tp", [""])[0] == "s" else "long",
                "value": trade.get("e", {}).get("p", 0),
                "time": trade.get("e", {}).get("tm", 0),
            },
            "exit": {
                "name": trade.get("x", {}).get("c", ""),
                "value": trade.get("x", {}).get("p", 0),
                "time": trade.get("x", {}).get("tm", 0),
            },
            "quantity": trade.get("q", 0),
            "profit": trade.get("tp", {}),
            "cumulative": trade.get("cp", {}),
            "runup": trade.get("rn", {}),
            "drawdown": trade.get("dd", {}),
        })
    return result


class ChartStudy:
    """Chart study/indicator handler.
    
    Matches JS ChartStudy implementation.
    """
    
    def __init__(self, chart_session, indicator):
        if not isinstance(indicator, (PineIndicator, BuiltInIndicator)):
            raise IndicatorError(
                "Indicator argument must be an instance of PineIndicator or BuiltInIndicator. "
                "Please use 'get_indicator(...)' function.",
                None,
                {"receivedType": type(indicator).__name__}
            )
        
        self._stud_id = gen_session_id("st")
        self._chart_session = chart_session
        self.instance = indicator
        self._periods = {}
        self._cached_periods = None
        self._periods_modified = False
        self._indexes = []
        self._graphic = {}
        self._strategy_report = {
            "trades": [],
            "history": {},
            "performance": {},
        }
        self._callbacks = {
            "studyCompleted": [],
            "update": [],
            "error": [],
            "event": [],
        }
        
        # Register study listener
        chart_session["studyListeners"][self._stud_id] = self._on_data
        
        # Create study
        inputs = self._get_inputs(indicator)
        chart_session["send"]("create_study", [
            chart_session["sessionID"],
            self._stud_id,
            "st1",
            "$prices",
            indicator.type,
            inputs
        ])
    
    def _get_inputs(self, indicator):
        """Get indicator inputs formatted for API.
        
        Matches JS getInputs implementation.
        """
        if isinstance(indicator, PineIndicator):
            pine_inputs = {"text": indicator.script}
            
            if indicator.pine_id:
                pine_inputs["pineId"] = indicator.pine_id
            if indicator.pine_version:
                pine_inputs["pineVersion"] = indicator.pine_version
            
            for input_id, input_data in indicator.inputs.items():
                # For color types, use the index as value
                value = input_data.get("value")
                if input_data.get("type") == "color":
                    # Get index of this input among all inputs
                    value = list(indicator.inputs.keys()).index(input_id)
                
                pine_inputs[input_id] = {
                    "v": value,
                    "f": input_data.get("isFake", False),
                    "t": input_data["type"]
                }
            
            return pine_inputs
        
        return indicator.options
    
    def _on_data(self, packet):
        """Handle incoming study data."""
        if packet["type"] == "study_completed":
            self._trigger_event("studyCompleted")
            self._trigger_event("event", "studyCompleted")
            return

        if packet["type"] in ["timescale_update", "du"]:
            changes = []
            data = packet["data"][1].get(self._stud_id, {})

            # Handle plots
            if data and data.get("st") and data["st"]:
                for p in data["st"]:
                    period = {}
                    
                    for i, plot in enumerate(p["v"]):
                        if not self.instance.plots:
                            plot_name = "$time" if i == 0 else f"plot_{i-1}"
                            period[plot_name] = plot
                        else:
                            plot_name = "$time" if i == 0 else self.instance.plots.get(f"plot_{i-1}")
                            if plot_name and plot_name not in period:
                                period[plot_name] = plot
                            else:
                                period[f"plot_{i-1}"] = plot
                    
                    self._periods[p["v"][0]] = period
                
                self._periods_modified = True
                changes.append("plots")

            # Handle namespace payloads (graphics, strategy reports, etc.)
            ns = data.get("ns", {})
            if ns and ns.get("d"):
                raw_data = ns["d"]
                try:
                    parsed = json.loads(raw_data)
                except json.JSONDecodeError as e:
                    if is_debug_enabled():
                        print(f"Study parse error: {e}")
                    parsed = None
                
                if parsed:
                    # graphics commands
                    if parsed.get("graphicsCmds"):
                        cmds = parsed["graphicsCmds"]
                        # erasure instructions
                        if cmds.get("erase"):
                            for instr in cmds["erase"]:
                                if instr.get("action") == "all":
                                    if not instr.get("type"):
                                        for draw_type in list(self._graphic.keys()):
                                            self._graphic[draw_type] = {}
                                    else:
                                        self._graphic.pop(instr.get("type"), None)
                                    continue
                                
                                if instr.get("action") == "one":
                                    self._graphic.get(instr.get("type"), {}).pop(instr.get("id"), None)
                        
                        # create instructions
                        if cmds.get("create"):
                            for draw_type, groups in cmds["create"].items():
                                if draw_type not in self._graphic:
                                    self._graphic[draw_type] = {}
                                for group in groups:
                                    for item in group.get("data", []):
                                        self._graphic[draw_type][item["id"]] = item
                        
                        changes.append("graphic")
                    
                    # strategy report updates
                    if parsed.get("report"):
                        report = parsed["report"]
                        if report.get("currency"):
                            self._strategy_report["currency"] = report["currency"]
                            changes.append("report.currency")
                        if report.get("settings"):
                            self._strategy_report["settings"] = report["settings"]
                            changes.append("report.settings")
                        if report.get("performance"):
                            self._strategy_report["performance"] = report["performance"]
                            changes.append("report.perf")
                        if report.get("trades"):
                            self._strategy_report["trades"] = _parse_trades(report["trades"])
                            changes.append("report.trades")
                        if report.get("equity"):
                            self._strategy_report["history"] = {
                                "buyHold": report.get("buyHold"),
                                "buyHoldPercent": report.get("buyHoldPercent"),
                                "drawDown": report.get("drawDown"),
                                "drawDownPercent": report.get("drawDownPercent"),
                                "equity": report.get("equity"),
                                "equityPercent": report.get("equityPercent"),
                            }
                            changes.append("report.history")
            
            # Handle compressed data
            if ns and ns.get("dCompressed"):
                async def _process_compressed(compressed_data):
                    try:
                        parsed = await Protocol.parse_compressed(compressed_data)
                        if parsed and parsed.get("report"):
                            report = parsed["report"]
                            if report.get("currency"):
                                self._strategy_report["currency"] = report["currency"]
                            if report.get("settings"):
                                self._strategy_report["settings"] = report["settings"]
                            if report.get("performance"):
                                self._strategy_report["performance"] = report["performance"]
                            if report.get("trades"):
                                self._strategy_report["trades"] = _parse_trades(report["trades"])
                            if report.get("equity"):
                                self._strategy_report["history"] = {
                                    "buyHold": report.get("buyHold"),
                                    "buyHoldPercent": report.get("buyHoldPercent"),
                                    "drawDown": report.get("drawDown"),
                                    "drawDownPercent": report.get("drawDownPercent"),
                                    "equity": report.get("equity"),
                                    "equityPercent": report.get("equityPercent"),
                                }
                            self._trigger_event("update", ["report.compressed"])
                    except Exception as e:
                        if is_debug_enabled():
                            print(f"Error processing compressed data: {e}")
                
                asyncio.create_task(_process_compressed(ns["dCompressed"]))
            
            # Handle indexes
            if ns and ns.get("indexes") and isinstance(ns["indexes"], (list, dict)):
                self._indexes = ns["indexes"]

            self._trigger_event("update", changes)
            self._trigger_event("event", "update", changes)
            return
        
        if packet["type"] == "study_error":
            error = IndicatorError(
                packet["data"][3] if len(packet["data"]) > 3 else "Study error",
                self.instance.pine_id if hasattr(self.instance, "pine_id") else None,
                packet["data"][4] if len(packet["data"]) > 4 else None
            )
            self._trigger_event("error", error)
            self._trigger_event("event", "error", error)
    
    def _trigger_event(self, event: str, *args):
        """Trigger event callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(*args))
                else:
                    callback(*args)
            except Exception as e:
                if is_debug_enabled():
                    print(f"Error in callback: {e}")
    
    @property
    def periods(self) -> List[Dict]:
        """Get sorted periods."""
        if self._periods_modified or not self._cached_periods:
            self._cached_periods = sorted(
                self._periods.values(),
                key=lambda x: x.get("$time", 0),
                reverse=True
            )
            self._periods_modified = False
        return self._cached_periods
    
    @property
    def graphic(self):
        """Get graphic data with proper parsing.
        
        Matches JS graphic getter with index translation.
        """
        # Build translator from chart session indexes
        translator = {}
        indexes_map = self._chart_session.get("indexes", {})
        
        for idx, time_val in sorted(indexes_map.items(), key=lambda x: x[1], reverse=True):
            translator[idx] = len(translator)
        
        # Translate indexes
        translated_indexes = [translator.get(i, i) for i in self._indexes]
        
        # Return parsed graphic (simplified - full parsing would use graphicParser)
        return self._graphic
    
    @property
    def strategy_report(self) -> Dict:
        """Get strategy report."""
        return self._strategy_report
    
    def set_indicator(self, indicator):
        """Change the indicator after creation.
        
        Matches JS setIndicator implementation.
        """
        if not isinstance(indicator, (PineIndicator, BuiltInIndicator)):
            raise IndicatorError(
                "Indicator argument must be an instance of PineIndicator or BuiltInIndicator.",
                None,
                {"receivedType": type(indicator).__name__}
            )
        
        self.instance = indicator
        
        inputs = self._get_inputs(indicator)
        self._chart_session["send"]("modify_study", [
            self._chart_session["sessionID"],
            self._stud_id,
            "st1",
            inputs
        ])
    
    def on_ready(self, callback: Callable):
        """Register callback for when study is ready.
        
        JS equivalent: onReady
        """
        self._callbacks["studyCompleted"].append(callback)
        return lambda: self._remove_callback("studyCompleted", callback)
    
    def on_update(self, callback: Callable):
        """Register callback for updates."""
        self._callbacks["update"].append(callback)
        return lambda: self._remove_callback("update", callback)
    
    def on_error(self, callback: Callable):
        """Register callback for errors."""
        self._callbacks["error"].append(callback)
        return lambda: self._remove_callback("error", callback)
    
    def on_event(self, callback: Callable):
        """Register callback for all events."""
        self._callbacks["event"].append(callback)
        return lambda: self._remove_callback("event", callback)
    
    def _remove_callback(self, event: str, callback: Callable):
        """Remove a callback."""
        if callback in self._callbacks.get(event, []):
            self._callbacks[event].remove(callback)
    
    def remove(self):
        """Remove the study."""
        self._chart_session["send"]("remove_study", [
            self._chart_session["sessionID"],
            self._stud_id
        ])
        if self._stud_id in self._chart_session.get("studyListeners", {}):
            del self._chart_session["studyListeners"][self._stud_id]


# ============================================================================
# CHART SESSION
# ============================================================================

class ChartSession:
    """Chart session handler.
    
    Matches JS ChartSession implementation with replay mode support,
    timezone switching, and all event callbacks.
    """
    
    # Chart type mappings
    CHART_TYPES = {
        "HeikinAshi": "BarSetHeikenAshi@tv-basicstudies-60!",
        "Renko": "BarSetRenko@tv-prostudies-40!",
        "LineBreak": "BarSetPriceBreak@tv-prostudies-34!",
        "Kagi": "BarSetKagi@tv-prostudies-34!",
        "PointAndFigure": "BarSetPnF@tv-prostudies-34!",
        "Range": "BarSetRange@tv-basicstudies-72!",
    }
    
    def __init__(self, client):
        self._chart_session_id = gen_session_id("cs")
        self._replay_session_id = gen_session_id("rs")
        self._client = client
        self._study_listeners = {}
        self._periods = {}
        self._cached_periods = None
        self._periods_modified = False
        self._infos = {}
        self._callbacks = {
            "symbolLoaded": [],
            "update": [],
            "error": [],
            "event": [],
            "replayLoaded": [],
            "replayPoint": [],
            "replayResolution": [],
            "replayEnd": [],
        }
        self._series_created = False
        self._current_series = 0
        self._indexes = {}
        self._replay_mode = False
        self._replay_ok_callbacks = {}
        
        # Register sessions
        client._sessions[self._chart_session_id] = {
            "type": "chart",
            "onData": self._on_data
        }
        client._sessions[self._replay_session_id] = {
            "type": "replay",
            "onData": self._on_replay_data
        }
        
        # Create chart session
        client.send("chart_create_session", [self._chart_session_id])
    
    def _on_data(self, packet):
        """Handle incoming chart data."""
        if packet["type"] == "symbol_resolved":
            self._infos = {
                "series_id": packet["data"][1],
                **packet["data"][2]
            }
            self._trigger_event("symbolLoaded")
            self._trigger_event("event", "symbolLoaded")
            return
        
        if packet["type"] in ["timescale_update", "du"]:
            changes = []
            data = packet["data"][1]
            
            for key in data.keys():
                changes.append(key)
                if key == "$prices":
                    periods = data["$prices"]
                    if periods and periods.get("s"):
                        for p in periods["s"]:
                            self._indexes[p["i"]] = p["v"][0]
                            self._periods[p["v"][0]] = {
                                "time": p["v"][0],
                                "open": p["v"][1],
                                "close": p["v"][4],
                                "max": p["v"][2],
                                "min": p["v"][3],
                                "volume": round(p["v"][5] * 100) / 100
                            }
                    self._periods_modified = True
                elif key in self._study_listeners:
                    self._study_listeners[key](packet)
            
            self._trigger_event("update", changes)
            self._trigger_event("event", "update", changes)
            return
        
        if packet["type"] == "symbol_error":
            error = SymbolError(
                packet["data"][2] if len(packet["data"]) > 2 else "Symbol error",
                packet["data"][1] if len(packet["data"]) > 1 else None
            )
            self._trigger_event("error", error)
            self._trigger_event("event", "error", error)
            return
        
        if packet["type"] == "series_error":
            error = SessionError(
                packet["data"][3] if len(packet["data"]) > 3 else "Series error"
            )
            self._trigger_event("error", error)
            self._trigger_event("event", "error", error)
            return
        
        if packet["type"] == "critical_error":
            name = packet["data"][1] if len(packet["data"]) > 1 else "Unknown"
            description = packet["data"][2] if len(packet["data"]) > 2 else ""
            error = SessionError(f"Critical error: {name}", description)
            self._trigger_event("error", error)
            self._trigger_event("event", "error", error)
    
    def _on_replay_data(self, packet):
        """Handle incoming replay data."""
        if packet["type"] == "replay_ok":
            req_id = packet["data"][1] if len(packet["data"]) > 1 else None
            if req_id and req_id in self._replay_ok_callbacks:
                self._replay_ok_callbacks[req_id]()
                del self._replay_ok_callbacks[req_id]
            return
        
        if packet["type"] == "replay_instance_id":
            self._trigger_event("replayLoaded", packet["data"][1] if len(packet["data"]) > 1 else None)
            self._trigger_event("event", "replayLoaded", packet["data"][1] if len(packet["data"]) > 1 else None)
            return
        
        if packet["type"] == "replay_point":
            self._trigger_event("replayPoint", packet["data"][1] if len(packet["data"]) > 1 else None)
            self._trigger_event("event", "replayPoint", packet["data"][1] if len(packet["data"]) > 1 else None)
            return
        
        if packet["type"] == "replay_resolutions":
            self._trigger_event("replayResolution", 
                packet["data"][1] if len(packet["data"]) > 1 else None,
                packet["data"][2] if len(packet["data"]) > 2 else None
            )
            self._trigger_event("event", "replayResolution",
                packet["data"][1] if len(packet["data"]) > 1 else None,
                packet["data"][2] if len(packet["data"]) > 2 else None
            )
            return
        
        if packet["type"] == "replay_data_end":
            self._trigger_event("replayEnd")
            self._trigger_event("event", "replayEnd")
            return
        
        if packet["type"] == "critical_error":
            name = packet["data"][1] if len(packet["data"]) > 1 else "Unknown"
            description = packet["data"][2] if len(packet["data"]) > 2 else ""
            error = SessionError(f"Critical error: {name}", description)
            self._trigger_event("error", error)
            self._trigger_event("event", "error", error)
    
    def _trigger_event(self, event: str, *args):
        """Trigger event callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(*args))
                else:
                    callback(*args)
            except Exception as e:
                if is_debug_enabled():
                    print(f"Error in callback: {e}")
    
    @property
    def periods(self) -> List[Dict]:
        """Get sorted periods."""
        if self._periods_modified or not self._cached_periods:
            self._cached_periods = sorted(
                self._periods.values(),
                key=lambda x: x["time"],
                reverse=True
            )
            self._periods_modified = False
        return self._cached_periods
    
    @property
    def infos(self) -> Dict:
        """Get market info."""
        return self._infos
    
    def set_market(self, symbol: str, **options):
        """Set chart market.
        
        Matches JS implementation with full support for:
        - timeframe, range, to (reference)
        - adjustment, backadjustment, session, currency
        - type (custom chart types)
        - replay mode
        """
        self._periods = {}
        self._periods_modified = True
        
        # Handle replay mode cleanup if needed
        if self._replay_mode and not options.get("replay"):
            self._replay_mode = False
            self._client.send("replay_delete_session", [self._replay_session_id])
        
        # Build symbol init
        symbol_init = {
            "symbol": symbol or "BTCEUR",
            "adjustment": options.get("adjustment", "splits"),
        }
        
        if options.get("backadjustment"):
            symbol_init["backadjustment"] = "default"
        if options.get("session"):
            symbol_init["session"] = options["session"]
        if options.get("currency"):
            symbol_init["currency-id"] = options["currency"]
        
        # Handle replay mode
        if options.get("replay"):
            if not self._replay_mode:
                self._replay_mode = True
                self._client.send("replay_create_session", [self._replay_session_id])
            
            self._client.send("replay_add_series", [
                self._replay_session_id,
                "req_replay_addseries",
                f"={json.dumps(symbol_init)}",
                options.get("timeframe", "240"),
            ])
            
            self._client.send("replay_reset", [
                self._replay_session_id,
                "req_replay_reset",
                options["replay"],
            ])
        
        # Handle custom chart types
        chart_type = options.get("type")
        is_complex = chart_type or options.get("replay")
        
        if is_complex:
            chart_init = {}
            if options.get("replay"):
                chart_init["replay"] = self._replay_session_id
            chart_init["symbol"] = symbol_init
            if chart_type:
                chart_init["type"] = self.CHART_TYPES.get(chart_type, chart_type)
                if options.get("inputs"):
                    chart_init["inputs"] = {**options["inputs"]}
        else:
            chart_init = symbol_init
        
        self._current_series += 1
        
        self._client.send("resolve_symbol", [
            self._chart_session_id,
            f"ser_{self._current_series}",
            f"={json.dumps(chart_init)}",
        ])
        
        # Set series
        self.set_series(
            options.get("timeframe", "240"),
            options.get("range", 100),
            options.get("to")
        )
    
    def set_series(self, timeframe: str = "240", range_val: int = 100, reference: Optional[int] = None):
        """Set chart series."""
        if not self._current_series:
            raise SessionError("Please set the market before setting series")
        
        calc_range = range_val if reference is None else ["bar_count", reference, range_val]
        self._periods = {}
        self._periods_modified = True
        
        self._client.send(
            "modify_series" if self._series_created else "create_series",
            [
                self._chart_session_id,
                "$prices",
                "s1",
                f"ser_{self._current_series}",
                timeframe,
                "" if self._series_created else calc_range
            ]
        )
        
        self._series_created = True
    
    def set_timezone(self, timezone: str):
        """Set the chart timezone."""
        self._periods = {}
        self._periods_modified = True
        self._client.send("switch_timezone", [self._chart_session_id, timezone])
    
    def fetch_more(self, number: int = 1):
        """Fetch additional previous periods/candles."""
        self._client.send("request_more_data", [self._chart_session_id, "$prices", number])
    
    async def replay_step(self, number: int = 1) -> None:
        """Step forward in replay mode.
        
        Returns a Future that resolves when the step is complete.
        """
        if not self._replay_mode:
            raise SessionError("No replay session")
        
        req_id = gen_session_id("rsq_step")
        fut = asyncio.get_event_loop().create_future()
        
        def on_ok():
            if not fut.done():
                fut.set_result(None)
        
        self._replay_ok_callbacks[req_id] = on_ok
        self._client.send("replay_step", [self._replay_session_id, req_id, number])
        
        return await fut
    
    async def replay_start(self, interval: int = 1000) -> None:
        """Start automatic replay mode.
        
        Args:
            interval: Milliseconds between each candle
        """
        if not self._replay_mode:
            raise SessionError("No replay session")
        
        req_id = gen_session_id("rsq_start")
        fut = asyncio.get_event_loop().create_future()
        
        def on_ok():
            if not fut.done():
                fut.set_result(None)
        
        self._replay_ok_callbacks[req_id] = on_ok
        self._client.send("replay_start", [self._replay_session_id, req_id, interval])
        
        return await fut
    
    async def replay_stop(self) -> None:
        """Stop automatic replay mode."""
        if not self._replay_mode:
            raise SessionError("No replay session")
        
        req_id = gen_session_id("rsq_stop")
        fut = asyncio.get_event_loop().create_future()
        
        def on_ok():
            if not fut.done():
                fut.set_result(None)
        
        self._replay_ok_callbacks[req_id] = on_ok
        self._client.send("replay_stop", [self._replay_session_id, req_id])
        
        return await fut

    async def fetch_history(self, count: int = 100, timeout: float = 20000) -> List[Dict]:
        """Wait until at least ``count`` periods have been received.

        Returns a list of period dicts or raises ``asyncio.CancelledError`` if
        the timeout expires.
        """
        loop = asyncio.get_event_loop()
        fut = loop.create_future()

        def _on_update(changes):
            if len(self.periods) >= count and not fut.done():
                fut.set_result(self.periods[:count])
        
        self.on_update(_on_update)
        timer = loop.call_later(timeout/1000, lambda: fut.cancel())
        try:
            return await fut
        finally:
            self._remove_callback("update", _on_update)
            timer.cancel()
    
    def on_symbol_loaded(self, callback: Callable):
        """Register callback for symbol loaded event."""
        self._callbacks["symbolLoaded"].append(callback)
        return lambda: self._remove_callback("symbolLoaded", callback)
    
    def on_update(self, callback: Callable):
        """Register callback for update event."""
        self._callbacks["update"].append(callback)
        return lambda: self._remove_callback("update", callback)
    
    def on_error(self, callback: Callable):
        """Register callback for error event."""
        self._callbacks["error"].append(callback)
        return lambda: self._remove_callback("error", callback)
    
    def on_event(self, callback: Callable):
        """Register callback for all events."""
        self._callbacks["event"].append(callback)
        return lambda: self._remove_callback("event", callback)
    
    def on_replay_loaded(self, callback: Callable):
        """Register callback for replay loaded event."""
        self._callbacks["replayLoaded"].append(callback)
        return lambda: self._remove_callback("replayLoaded", callback)
    
    def on_replay_point(self, callback: Callable):
        """Register callback for replay point event."""
        self._callbacks["replayPoint"].append(callback)
        return lambda: self._remove_callback("replayPoint", callback)
    
    def on_replay_resolution(self, callback: Callable):
        """Register callback for replay resolution event."""
        self._callbacks["replayResolution"].append(callback)
        return lambda: self._remove_callback("replayResolution", callback)
    
    def on_replay_end(self, callback: Callable):
        """Register callback for replay end event."""
        self._callbacks["replayEnd"].append(callback)
        return lambda: self._remove_callback("replayEnd", callback)
    
    def _remove_callback(self, event: str, callback: Callable):
        """Remove a callback."""
        if callback in self._callbacks.get(event, []):
            self._callbacks[event].remove(callback)
    
    def create_study(self, indicator):
        """Create a new study.
        
        DEPRECATED: Use chart.Study(indicator) instead to match JS API.
        """
        return self.Study(indicator)
    
    def Study(self, indicator):
        """Create a new study.
        
        Matches JS chart.Study(indicator) API.
        """
        return ChartStudy({
            "sessionID": self._chart_session_id,
            "studyListeners": self._study_listeners,
            "indexes": self._indexes,
            "send": self._client.send
        }, indicator)
    
    def delete(self):
        """Delete the chart session."""
        if self._replay_mode:
            self._client.send("replay_delete_session", [self._replay_session_id])
        self._client.send("chart_delete_session", [self._chart_session_id])
        if self._chart_session_id in self._client._sessions:
            del self._client._sessions[self._chart_session_id]
        if self._replay_session_id in self._client._sessions:
            del self._client._sessions[self._replay_session_id]
        self._replay_mode = False


# ============================================================================
# QUOTE SESSION
# ============================================================================

class QuoteMarket:
    """Quote market handler."""
    
    def __init__(self, quote_session, symbol: str, session: str = "regular"):
        self._quote_session = quote_session
        self._symbol = symbol
        self._session = session
        self._symbol_key = f"={json.dumps({'session': session, 'symbol': symbol})}"
        self._last_data = {}
        self._callbacks = {
            "loaded": [],
            "data": [],
            "error": []
        }
        
        # Register listener
        if self._symbol_key not in quote_session["symbolListeners"]:
            quote_session["symbolListeners"][self._symbol_key] = []
            quote_session["send"]("quote_add_symbols", [
                quote_session["sessionID"],
                self._symbol_key
            ])
        
        self._listener_id = len(quote_session["symbolListeners"][self._symbol_key])
        quote_session["symbolListeners"][self._symbol_key].append(self._on_data)
    
    def _on_data(self, packet):
        """Handle incoming quote data."""
        if packet["type"] == "quote_completed":
            self._trigger_event("loaded")
            return
        
        if packet["type"] == "qsd" and packet["data"][1].get("s") == "ok":
            self._last_data.update(packet["data"][1].get("v", {}))
            self._trigger_event("data", self._last_data)
    
    def _trigger_event(self, event: str, *args):
        """Trigger event callbacks."""
        for callback in self._callbacks.get(event, []):
            callback(*args)
    
    def on_loaded(self, callback: Callable):
        """Register callback for loaded event."""
        self._callbacks["loaded"].append(callback)
    
    def on_data(self, callback: Callable):
        """Register callback for data event."""
        self._callbacks["data"].append(callback)
    
    def on_error(self, callback: Callable):
        """Register callback for error event."""
        self._callbacks["error"].append(callback)
    
    def close(self):
        """Close this market listener."""
        self._quote_session["send"]("quote_remove_symbols", [
            self._quote_session["sessionID"],
            self._symbol_key
        ])


class QuoteSession:
    """Quote session handler."""
    
    def __init__(self, client, **options):
        self._session_id = gen_session_id("qs")
        self._client = client
        self._symbol_listeners = {}
        
        # Register session
        client._sessions[self._session_id] = {
            "type": "quote",
            "onData": self._on_data
        }
        
        # Create quote session
        client.send("quote_create_session", [self._session_id])
        
        # Set fields
        fields = options.get("customFields", self._get_quote_fields(options.get("fields", "all")))
        client.send("quote_set_fields", [self._session_id, *fields])
    
    def _get_quote_fields(self, fields_type: str) -> List[str]:
        """Get quote fields."""
        if fields_type == "price":
            return ["lp"]
        
        return [
            "base-currency-logoid", "ch", "chp", "currency-logoid",
            "currency_code", "current_session", "description",
            "exchange", "format", "fractional", "is_tradable",
            "lp", "lp_time", "minmov", "minmove2", "original_name",
            "pricescale", "pro_name", "short_name", "type",
            "volume", "ask", "bid", "high_price", "low_price",
            "open_price", "prev_close_price"
        ]
    
    def _on_data(self, packet):
        """Handle incoming quote data."""
        if packet["type"] == "quote_completed":
            symbol_key = packet["data"][1]
            if symbol_key in self._symbol_listeners:
                for handler in self._symbol_listeners[symbol_key]:
                    handler(packet)
        
        if packet["type"] == "qsd":
            symbol_key = packet["data"][1].get("n")
            if symbol_key in self._symbol_listeners:
                for handler in self._symbol_listeners[symbol_key]:
                    handler(packet)
    
    def create_market(self, symbol: str, session: str = "regular"):
        """Create a market quote."""
        return QuoteMarket({
            "sessionID": self._session_id,
            "symbolListeners": self._symbol_listeners,
            "send": self._client.send
        }, symbol, session)
    
    def delete(self):
        """Delete the quote session."""
        self._client.send("quote_delete_session", [self._session_id])
        del self._client._sessions[self._session_id]


# ============================================================================
# CLIENT
# ============================================================================

class Client:
    """TradingView WebSocket client.
    
    Matches the JS Client implementation with:
    - location parameter for proper origin handling
    - token/signature authentication
    - onConnected/onError callbacks with unsubscribe functions
    - Proper connection state management
    """

    def __init__(self, **options):
        self._ws = None
        self._logged = False
        self._handshake_received = False
        self._is_shutting_down = False
        self._sessions = {}
        self._send_queue = []
        self._callbacks = {
            "connected": [],
            "disconnected": [],
            "logged": [],
            "ping": [],
            "data": [],
            "log": [],
            "error": [],
            "event": [],
            "reconnecting": [],
            "reconnected": [],
            "reconnectFailed": [],
            "pingTimeout": [],
        }
        self._server = options.get("server", "data")
        self._token = options.get("token")
        self._signature = options.get("signature", "")
        self._location = options.get("location", "https://www.tradingview.com/")
        self._running = False
        self._connected = False
        
        # Set debug mode if requested
        if options.get("debug") is not None:
            set_debug(options.get("debug"))
        if options.get("DEBUG") is not None:
            set_debug(options.get("DEBUG"))
    
    @property
    def is_logged(self) -> bool:
        """If the client is logged in."""
        return self._logged
    
    @property
    def is_open(self) -> bool:
        """If the WebSocket is open."""
        if self._ws is None:
            return False
        from websockets.protocol import State
        return self._ws.state == State.OPEN
    
    def _remove_callback(self, event: str, callback: Callable):
        """Remove a callback."""
        if callback in self._callbacks.get(event, []):
            self._callbacks[event].remove(callback)
    
    def _handle_event(self, event: str, *args):
        """Handle event and trigger callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(*args))
                else:
                    callback(*args)
            except Exception as e:
                if is_debug_enabled():
                    print(f"Error in event callback: {e}")
        
        # Also trigger event callback for all events
        for callback in self._callbacks.get("event", []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(event, *args))
                else:
                    callback(event, *args)
            except Exception as e:
                if is_debug_enabled():
                    print(f"Error in event callback: {e}")
    
    def _handle_error(self, *msgs):
        """Handle error."""
        error_obj = msgs[0] if isinstance(msgs[0], Exception) else Exception(" ".join(str(m) for m in msgs))
        if not self._callbacks.get("error"):
            print(f"Error: {error_obj}")
        else:
            self._handle_event("error", error_obj, *msgs[1:])
    
    async def connect(self):
        """Connect to TradingView WebSocket.
        
        Matches JS implementation: uses location-based origin and proper
        cookie handling for authenticated connections.
        """
        if self._is_shutting_down:
            return
        
        uri = f"wss://{self._server}.tradingview.com/socket.io/websocket?type=chart"

        # Build cookies header if we have session/signature
        additional_headers = {
            "Origin": self._location.rstrip("/"),
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        
        # Get auth token from session/signature if provided
        auth_token = "unauthorized_user_token"
        if self._token:
            try:
                user = await get_user(self._token, self._signature, self._location)
                auth_token = user.get("authToken", self._token)
            except Exception as e:
                error = AuthenticationError("Credentials error", str(e))
                self._handle_error(error)
                raise error
        
        # Add cookies to headers if we have them
        if self._token or self._signature:
            additional_headers["Cookie"] = gen_auth_cookies(self._token, self._signature)

        try:
            self._ws = await websockets.connect(
                uri,
                origin=self._location.rstrip("/"),
                additional_headers=additional_headers
            )
        except Exception as e:
            raise ConnectionError(f"Failed to connect: {e}")

        self._running = True

        # Send auth token immediately
        self._send_queue.insert(0, Protocol.format_ws_packet({
            "m": "set_auth_token",
            "p": [auth_token]
        }))
        self._logged = True
        self._handle_event("connected")
        await self._send_queued()

        # Start listening
        asyncio.create_task(self._listen())

    async def wait_for_connected(self, timeout_ms: int = 15000) -> bool:
        """Wait for connection to be established.
        
        Matches JS waitForConnected implementation with timeout and fallback.
        Returns True if connected, False if timeout or error.
        """
        timeout_sec = timeout_ms / 1000
        start_time = asyncio.get_event_loop().time()
        
        while self._running and not self._connected:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout_sec:
                return False
            await asyncio.sleep(0.1)
        
        return self._connected
    
    async def _listen(self):
        """Listen for incoming messages.

        Matches JS implementation with proper error handling and connection
        state tracking.
        """
        try:
            self._connected = True
            async for message in self._ws:
                if is_debug_enabled():
                    print(f"[DEBUG] Received: {message[:200]}...")
                await self._parse_packet(message)
        except websockets.exceptions.ConnectionClosed:
            # Connection closed normally or abnormally
            pass
        except Exception as e:
            self._handle_event("error", e)
        finally:
            self._connected = False
            self._logged = False
            self._running = False
            self._handle_event("disconnected")
    
    async def _parse_packet(self, data: str):
        """Parse incoming packet."""
        if not self.is_open:
            return
        
        packets = Protocol.parse_ws_packet(data)

        for packet in packets:
            if is_debug_enabled():
                print(f"[DEBUG] Packet: {packet}")
            
            # Handle ping
            if isinstance(packet, int):
                await self._ws.send(Protocol.format_ws_packet(f"~h~{packet}"))
                self._handle_event("ping", packet)
                continue

            # Handle handshake - emit logged event
            if not self._handshake_received and isinstance(packet, dict) and packet.get("session_id"):
                self._handshake_received = True
                self._handle_event("logged", packet)
                continue

            # Before auth token is ready, ignore non-ping traffic
            if not self._logged:
                continue

            # Handle normal packet
            if isinstance(packet, dict):
                if packet.get("m") == "protocol_error":
                    error = ConnectionError("Client protocol error", packet.get("p"))
                    self._handle_error(error, packet.get("p"))
                    await self._ws.close()
                    continue

                if packet.get("m") and packet.get("p"):
                    parsed = {
                        "type": packet["m"],
                        "data": packet["p"]
                    }

                    session_id = packet["p"][0] if packet["p"] else None
                    if session_id and session_id in self._sessions:
                        self._sessions[session_id]["onData"](parsed)
                        continue

                self._handle_event("data", packet)
    
    def send(self, msg_type: str, params: List = None):
        """Send a message."""
        if params is None:
            params = []
        
        packet = Protocol.format_ws_packet({"m": msg_type, "p": params})
        self._send_queue.append(packet)
        asyncio.create_task(self._send_queued())
    
    async def _send_queued(self):
        """Send all queued messages."""
        while self.is_open and self._logged and self._send_queue:
            try:
                packet = self._send_queue.pop(0)
                await self._ws.send(packet)
                if is_debug_enabled():
                    print(f"[DEBUG] Sent: {packet[:100]}...")
            except websockets.exceptions.ConnectionClosed:
                self._logged = False
                self._running = False
                self._handle_event("disconnected")
                break
            except Exception as e:
                if is_debug_enabled():
                    print(f"[DEBUG] Send error: {e}")
                self._logged = False
                break
    
    def on_connected(self, callback: Callable):
        """Register callback for connected event.
        
        Returns a function to unsubscribe.
        """
        self._callbacks["connected"].append(callback)
        return lambda: self._remove_callback("connected", callback)
    
    def on_disconnected(self, callback: Callable):
        """Register callback for disconnected event.
        
        Returns a function to unsubscribe.
        """
        self._callbacks["disconnected"].append(callback)
        return lambda: self._remove_callback("disconnected", callback)
    
    def on_logged(self, callback: Callable):
        """Register callback for logged event.
        
        Returns a function to unsubscribe.
        """
        self._callbacks["logged"].append(callback)
        return lambda: self._remove_callback("logged", callback)
    
    def on_ping(self, callback: Callable):
        """Register callback for ping event.
        
        Returns a function to unsubscribe.
        """
        self._callbacks["ping"].append(callback)
        return lambda: self._remove_callback("ping", callback)
    
    def on_data(self, callback: Callable):
        """Register callback for raw data event.
        
        Returns a function to unsubscribe.
        """
        self._callbacks["data"].append(callback)
        return lambda: self._remove_callback("data", callback)
    
    def on_log(self, callback: Callable):
        """Register callback for log event.
        
        Returns a function to unsubscribe.
        """
        self._callbacks["log"].append(callback)
        return lambda: self._remove_callback("log", callback)
    
    def on_error(self, callback: Callable):
        """Register callback for error event.
        
        Returns a function to unsubscribe.
        """
        self._callbacks["error"].append(callback)
        return lambda: self._remove_callback("error", callback)
    
    def on_event(self, callback: Callable):
        """Register callback for all events.
        
        Returns a function to unsubscribe.
        """
        self._callbacks["event"].append(callback)
        return lambda: self._remove_callback("event", callback)
    
    def create_chart_session(self):
        """Create a chart session."""
        return ChartSession(self)
    
    def create_quote_session(self, **options):
        """Create a quote session."""
        return QuoteSession(self, **options)
    
    # Convenience properties for JS-like API
    @property
    def Session(self):
        """Session namespace for JS-like API."""
        class SessionNS:
            def __init__(inner_self, client):
                inner_self._client = client
            
            def Chart(inner_self):
                return ChartSession(inner_self._client)
            
            def Quote(inner_self, **options):
                return QuoteSession(inner_self._client, **options)
        
        return SessionNS(self)
    
    def Study(self, indicator):
        """Create a study - requires a chart session first.
        
        This is a convenience method. In practice, you should use chart.Study().
        """
        raise RuntimeError("Use chart.Study(indicator) instead of client.Study()")

    async def fetch_history(
        self,
        symbol: str,
        timeframe: str = "240",
        count: int = 100,
        to: Optional[int] = None,
        timeout: float = 20000,
    ) -> List[Dict]:
        """High-level helper that returns ``count`` bars for the given symbol.

        Creates a temporary chart session, loads the market, waits for
        enough periods using :meth:`ChartSession.fetch_history`, and cleans up
        when complete.
        """
        chart = self.create_chart_session()
        chart.set_market(symbol, timeframe=timeframe, range=count, to=to)
        try:
            periods = await chart.fetch_history(count, timeout)
            return periods
        finally:
            try:
                chart.delete()
            except Exception:
                pass
    
    async def end(self):
        """Close the WebSocket connection gracefully.
        
        Matches JS end() implementation.
        """
        self._is_shutting_down = True
        
        # Clean up all sessions
        for session_id in list(self._sessions.keys()):
            del self._sessions[session_id]
        
        # Clear send queue
        self._send_queue = []
        
        if not self._ws:
            return
        
        if self._ws.state == websockets.protocol.State.CLOSED:
            return
        
        # Close WebSocket
        try:
            await self._ws.close()
        except Exception:
            pass
        
        self._running = False
        self._logged = False
    
    async def close(self):
        """Close the WebSocket connection (alias for end())."""
        await self.end()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Main classes
    "Client",
    "ChartSession",
    "ChartStudy",
    "QuoteSession",
    "QuoteMarket",
    "PineIndicator",
    "BuiltInIndicator",
    "PineFacadeClient",
    # Protocol and utilities
    "Protocol",
    "gen_session_id",
    "gen_auth_cookies",
    "normalize_pine_id",
    "normalize_timeframe",
    "looks_like_pine_id",
    "extract_pine_id_from_response",
    "_parse_save_response",
    # HTTP API functions
    "get_indicator",
    "get_user",
    "get_private_indicators",
    "get_ta",
    "search_market_v3",
    "search_indicator",
    "login_user",
    # Configuration
    "set_debug",
    "is_debug_enabled",
    # Error classes
    "TradingViewAPIError",
    "ConnectionError",
    "ProtocolError",
    "ValidationError",
    "AuthenticationError",
    "SymbolError",
    "IndicatorError",
    "SessionError",
]