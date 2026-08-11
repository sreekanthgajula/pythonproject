import os
import requests
import pandas as pd
import hashlib
from datetime import datetime, date
from io import StringIO
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.symbol_utils import NoMarketDataError

INSTRUMENTS_URL = "https://api.kite.trade/instruments"
_instruments_df = None


def _update_env_file(key: str, value: str):
    """Write or update an environment variable in the root .env file."""
    # Find .env file in project directory or standard locations
    project_dir = get_config().get("project_dir")
    env_path = os.path.join(project_dir, ".env") if project_dir else ".env"
    
    if not os.path.exists(env_path):
        env_path = ".env"  # Fallback to current working directory
        
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    replaced = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            replaced = True
        else:
            new_lines.append(line)
            
    if not replaced:
        new_lines.append(f"{key}={value}\n")
        
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _get_instruments_df() -> pd.DataFrame:
    """Download and cache the instruments CSV from Zerodha."""
    global _instruments_df
    if _instruments_df is not None:
        return _instruments_df

    cache_dir = get_config().get("data_cache_dir")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "zerodha_instruments.csv")

    use_cache = False
    if os.path.exists(cache_file):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(cache_file)).date()
            if mtime == date.today():
                use_cache = True
        except Exception:
            pass

    if use_cache:
        try:
            _instruments_df = pd.read_csv(cache_file, encoding="utf-8")
            if not _instruments_df.empty:
                return _instruments_df
        except Exception:
            pass

    # Download
    print(f"[{datetime.now()}] Downloading Zerodha Master Instruments list...")
    try:
        response = requests.get(INSTRUMENTS_URL, timeout=30)
        response.raise_for_status()
        
        # Save to cache
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(response.text)
            
        _instruments_df = pd.read_csv(StringIO(response.text), encoding="utf-8")
        return _instruments_df
    except Exception as e:
        # If download fails but we have a stale cache, fall back to it
        if os.path.exists(cache_file):
            print(f"[WARNING] Zerodha instruments download failed ({e}). Falling back to cached list.")
            try:
                _instruments_df = pd.read_csv(cache_file, encoding="utf-8")
                return _instruments_df
            except Exception:
                pass
        raise RuntimeError(f"Failed to retrieve Zerodha instruments list: {e}")


def get_instrument_token(symbol: str) -> int:
    """Map a ticker symbol (e.g. INFY.NS or INFY) to its Zerodha instrument token."""
    symbol = symbol.upper()
    exchange = "NSE"
    tradingsymbol = symbol

    if symbol.endswith(".NS"):
        exchange = "NSE"
        tradingsymbol = symbol[:-3]
    elif symbol.endswith(".BO"):
        exchange = "BSE"
        tradingsymbol = symbol[:-3]

    df = _get_instruments_df()

    # Search for matching exchange and tradingsymbol
    matches = df[(df["tradingsymbol"] == tradingsymbol) & (df["exchange"] == exchange)]
    if matches.empty:
        # Fallback to searching only by tradingsymbol
        matches = df[df["tradingsymbol"] == tradingsymbol]

    if matches.empty:
        raise NoMarketDataError(
            symbol, symbol, f"No instrument token found in Zerodha database for symbol '{symbol}'."
        )

    return int(matches.iloc[0]["instrument_token"])


def get_zerodha_credentials():
    """Retrieve Zerodha API credentials from environment variables."""
    return {
        "api_key": os.environ.get("ZERODHA_API_KEY"),
        "api_secret": os.environ.get("ZERODHA_API_SECRET"),
        "api_url": os.environ.get("ZERODHA_API_URL", "https://api.kite.trade"),
        "access_token": os.environ.get("ZERODHA_ACCESS_TOKEN"),
        "request_token": os.environ.get("ZERODHA_REQUEST_TOKEN"),
    }


def _exchange_request_token(api_key: str, request_token: str, api_secret: str, api_url: str) -> str:
    """Exchange request token for access token and write it to .env."""
    checksum_str = api_key + request_token + api_secret
    checksum = hashlib.sha256(checksum_str.encode("utf-8")).hexdigest()

    url = f"{api_url}/session/token"
    data = {
        "api_key": api_key,
        "request_token": request_token,
        "checksum": checksum
    }

    print(f"[{datetime.now()}] Exchanging Zerodha request token for access token...")
    resp = requests.post(url, data=data, timeout=10)
    
    if resp.status_code != 200:
        try:
            error_msg = resp.json().get("message", resp.text)
        except Exception:
            error_msg = resp.text
        raise ValueError(f"Zerodha session exchange failed: {error_msg}")

    resp_json = resp.json()
    if resp_json.get("status") == "success":
        access_token = resp_json["data"]["access_token"]
        print(f"[{datetime.now()}] Successfully obtained Zerodha access token!")
        _update_env_file("ZERODHA_ACCESS_TOKEN", access_token)
        # Update current environment variable so subsequent code sees it
        os.environ["ZERODHA_ACCESS_TOKEN"] = access_token
        return access_token
    else:
        error_msg = resp_json.get("message", "Unknown error")
        raise ValueError(f"Failed to exchange Zerodha request token: {error_msg}")


def is_token_valid(api_key: str, access_token: str, api_url: str) -> bool:
    """Validate if the current access token is active by calling the user profile API."""
    if not access_token:
        return False
    url = f"{api_url}/user/profile"
    headers = {
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{access_token}"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        return response.status_code == 200
    except Exception:
        return False


def get_request_token_via_totp(user_id: str, password: str, api_key: str, twofa_pin: str = None) -> str:
    """Perform automated login to Zerodha using Username, Password, and TOTP interactive input."""
    from urllib.parse import urlparse, parse_qs
    
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://kite.zerodha.com/"
    }
    
    # 1. Login request
    login_url = "https://kite.zerodha.com/api/login"
    payload = {
        "user_id": user_id,
        "password": password
    }
    
    r = session.post(login_url, data=payload, headers=headers)
    res_data = r.json()
    
    if res_data.get("status") != "success":
        raise ValueError(f"Login failed: {res_data.get('message', r.text)}")
        
    request_id = res_data["data"]["request_id"]
    twofa_type = res_data["data"].get("twofa_type", "totp")
    
    # 2. Prompt user for TOTP if not provided
    if twofa_pin is None:
        print("\n" + "="*50)
        print("ZERODHA MFA / 2FA REQUIRED")
        print("="*50)
        try:
            twofa_pin = input(f"Enter 6-digit Zerodha {twofa_type} code: ").strip()
        except (EOFError, OSError):
            raise ZerodhaNotConfiguredError(
                "Interactive terminal prompt not available to request TOTP. "
                "Please run the server interactively or provide a valid request_token / access_token."
            )
        print("="*50 + "\n")
    
    # 3. 2FA request
    twofa_url = "https://kite.zerodha.com/api/twofa"
    twofa_payload = {
        "user_id": user_id,
        "request_id": request_id,
        "twofa_value": twofa_pin,
        "twofa_type": twofa_type
    }
    
    r = session.post(twofa_url, data=twofa_payload, headers=headers)
    res_data = r.json()
    
    if res_data.get("status") != "success":
        raise ValueError(f"2FA authentication failed: {res_data.get('message', r.text)}")
        
    # 4. Get the request token from connect URL
    connect_url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
    url = connect_url
    request_token = None
    
    for _ in range(10):
        try:
            r = session.get(url, headers=headers, allow_redirects=False)
        except Exception as e:
            # If the next redirect destination fails to connect (e.g. localhost callback),
            # check if the target URL itself contains the request_token before raising the error
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if "request_token" in params:
                request_token = params["request_token"][0]
                break
            raise e
            
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "request_token" in params:
            request_token = params["request_token"][0]
            break
            
        if r.status_code in [301, 302]:
            next_url = r.headers.get("Location")
            if not next_url:
                break
            if next_url.startswith("/"):
                next_url = "https://kite.zerodha.com" + next_url
                
            # Check if the next redirect location contains the request_token
            parsed = urlparse(next_url)
            params = parse_qs(parsed.query)
            if "request_token" in params:
                request_token = params["request_token"][0]
                break
                
            url = next_url
        else:
            parsed = urlparse(r.url)
            params = parse_qs(parsed.query)
            if "request_token" in params:
                request_token = params["request_token"][0]
            break
            
    if not request_token:
        raise ValueError("request_token not found in redirect chain.")
        
    return request_token


class ZerodhaNotConfiguredError(ValueError):
    pass


def get_access_token() -> str:
    """Retrieve or generate a valid access token for Zerodha API."""
    creds = get_zerodha_credentials()
    if not creds["api_key"] or not creds["api_secret"]:
        raise ZerodhaNotConfiguredError(
            "ZERODHA_API_KEY or ZERODHA_API_SECRET environment variable is not set."
        )

    # 1. If we have a token, check if it's still valid before returning it
    if creds["access_token"]:
        if is_token_valid(creds["api_key"], creds["access_token"], creds["api_url"]):
            return creds["access_token"]
        else:
            print("[INFO] Configured Zerodha access token is expired or invalid. Attempting re-authentication...")

    # 2. Try using the request token if present in env
    if creds["request_token"]:
        try:
            access_token = _exchange_request_token(
                creds["api_key"], creds["request_token"], creds["api_secret"], creds["api_url"]
            )
            # Re-verify exchanged token to make sure it's valid
            if is_token_valid(creds["api_key"], access_token, creds["api_url"]):
                return access_token
        except Exception as e:
            print(f"[WARNING] Request token exchange failed: {e}")

    # 3. Try Auto-Login with Username and Password + TOTP Prompt
    user_id = os.environ.get("ZERODHA_USERNAME")
    password = os.environ.get("ZERODHA_PASSWORD")
    if user_id and password:
        try:
            request_token = get_request_token_via_totp(user_id, password, creds["api_key"])
            _update_env_file("ZERODHA_REQUEST_TOKEN", request_token)
            os.environ["ZERODHA_REQUEST_TOKEN"] = request_token
            
            # Exchange new request token for access token
            access_token = _exchange_request_token(
                creds["api_key"], request_token, creds["api_secret"], creds["api_url"]
            )
            return access_token
        except Exception as e:
            print(f"[ERROR] Auto-login flow failed: {e}")

    # 4. Fallback to raising configuration error with manual login link
    login_url = f"https://kite.zerodha.com/connect/login?api_key={creds['api_key']}&v=3"
    raise ZerodhaNotConfiguredError(
        f"Zerodha access token is missing or expired. Please authenticate by visiting the login URL:\n\n"
        f"  {login_url}\n\n"
        f"After logging in, copy the `request_token` from the URL parameter "
        f"and set `ZERODHA_REQUEST_TOKEN=your_token` in your `.env` file.\n"
        f"Alternatively, set ZERODHA_USERNAME and ZERODHA_PASSWORD in your .env file "
        f"to automate this login next time."
    )



def get_zerodha_stock_df(symbol: str, start_date: str, end_date: str, interval: str = "day") -> pd.DataFrame:
    """Fetch historical candles for a stock from Zerodha and return as a DataFrame."""
    api_key = os.environ.get("ZERODHA_API_KEY")
    access_token = get_access_token()
    instrument_token = get_instrument_token(symbol)
    api_url = os.environ.get("ZERODHA_API_URL", "https://api.kite.trade")

    url = f"{api_url}/instruments/historical/{instrument_token}/{interval}"
    headers = {
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{access_token}"
    }
    params = {
        "from": start_date,
        "to": end_date
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Error fetching historical data from Zerodha for {symbol}: {e}")

    data = response.json()
    if data.get("status") != "success":
        error_msg = data.get("message", "Unknown error")
        raise RuntimeError(f"Zerodha API returned error: {error_msg}")

    candles = data.get("data", {}).get("candles", [])
    if not candles:
        raise NoMarketDataError(
            symbol, symbol, f"Zerodha returned no candle data between {start_date} and {end_date}."
        )

    records = []
    for c in candles:
        # candle format: [timestamp, open, high, low, close, volume, open_interest]
        dt_str = c[0] if interval != "day" else c[0][:10]
        records.append({
            "Date": dt_str,
            "Open": float(c[1]),
            "High": float(c[2]),
            "Low": float(c[3]),
            "Close": float(c[4]),
            "Volume": int(c[5])
        })

    return pd.DataFrame(records)


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Retrieve historical stock data for a given ticker and date range as a CSV string."""
    df = get_zerodha_stock_df(symbol, start_date, end_date)

    # Round price columns for cleaner output
    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    csv_string = df.to_csv(index=False)

    header = f"# Stock data for {symbol} from {start_date} to {end_date} (via Zerodha)\n"
    header += f"# Total records: {len(df)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string
