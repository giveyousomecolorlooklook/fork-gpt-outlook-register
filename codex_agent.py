"""Codex Agent Identity 注册（核心库）。

通过 ChatGPT accessToken + Ed25519 密钥对，调用 /v1/agent/register
获取 agent_runtime_id，生成 Codex CLI 可用的 auth.json。
绕过 add-phone 限制，不走 OAuth 流程。

原始脚本 by 久雾，集成适配 by DangoMeow。
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)

logger = logging.getLogger(__name__)

import platform

AUTHAPI_BASE = "https://auth.openai.com/api/accounts"
AGENT_VERSION = "0.144.6"
AGENT_HARNESS_ID = "codex-cli"

def _running_location() -> str:
    os_name = platform.system().lower()
    os_map = {"windows": "windows", "linux": "linux", "darwin": "macos"}
    return f"cli-{os_map.get(os_name, os_name)}"


def generate_ed25519_keypair() -> tuple[str, str]:
    """生成 Ed25519 密钥对。返回 (private_key_pkcs8_base64, public_key_ssh)。"""
    private_key = Ed25519PrivateKey.generate()

    pkcs8_der = private_key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    private_key_b64 = base64.b64encode(pkcs8_der).decode()

    pub_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    ssh_header = b"ssh-ed25519"
    blob = bytearray()
    blob.extend(len(ssh_header).to_bytes(4, "big"))
    blob.extend(ssh_header)
    blob.extend(len(pub_bytes).to_bytes(4, "big"))
    blob.extend(pub_bytes)
    public_key_ssh = f"ssh-ed25519 {base64.b64encode(bytes(blob)).decode()}"

    return private_key_b64, public_key_ssh


def _create_agent_session(proxy: str = ""):
    """创建独立的 HTTP session（curl_cffi 无指纹模拟，不伪装浏览器）。"""
    try:
        from curl_cffi.requests import Session as CffiSession
        s = CffiSession()
        s.trust_env = False
        if proxy:
            p = proxy
            if p.startswith("socks5://"):
                p = "socks5h://" + p[len("socks5://"):]
            s.proxies = {"https": p, "http": p}
        else:
            s.proxies = {"https": "", "http": ""}
        return s
    except ImportError:
        import requests as _req
        s = _req.Session()
        s.trust_env = False
        if proxy:
            p = proxy
            if p.startswith("socks5://"):
                p = "socks5h://" + p[len("socks5://"):]
            s.proxies = {"https": p, "http": p}
        return s


def register_codex_agent(
    access_token: str,
    public_key_ssh: str,
    proxy: str = "",
) -> str:
    """调用 /v1/agent/register 注册 agent，返回 agent_runtime_id。"""
    session = _create_agent_session(proxy)
    resp = session.post(
        f"{AUTHAPI_BASE}/v1/agent/register",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        json={
            "abom": {
                "agent_version": AGENT_VERSION,
                "agent_harness_id": AGENT_HARNESS_ID,
                "running_location": _running_location(),
            },
            "agent_public_key": public_key_ssh,
            "capabilities": ["responsesapi"],
            "ttl": None,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Agent register failed: HTTP {resp.status_code} {resp.text[:300]}")

    data = resp.json()
    agent_runtime_id = data.get("agent_runtime_id")
    if not agent_runtime_id:
        raise RuntimeError(f"No agent_runtime_id in response: {data}")
    return agent_runtime_id


def decode_jwt_claims(jwt_token: str) -> dict[str, Any]:
    """解码 JWT payload（不验证签名）。"""
    parts = jwt_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload_b64 = parts[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    return json.loads(base64.urlsafe_b64decode(payload_b64))


def extract_account_info(access_token: str) -> dict[str, str]:
    """从 accessToken JWT 提取 account_id, user_id, email, plan_type。"""
    claims = decode_jwt_claims(access_token)
    auth_info = claims.get("https://api.openai.com/auth", {})
    profile = claims.get("https://api.openai.com/profile", {})
    return {
        "account_id": auth_info.get("chatgpt_account_id", ""),
        "user_id": auth_info.get("chatgpt_user_id", ""),
        "email": profile.get("email", ""),
        "plan_type": auth_info.get("chatgpt_plan_type", "free"),
    }


def build_auth_json(
    agent_runtime_id: str,
    private_key_b64: str,
    account_id: str,
    user_id: str,
    email: str,
    plan_type: str = "free",
) -> dict[str, Any]:
    """组装 Codex CLI 的 auth.json。"""
    return {
        "auth_mode": "agent_identity",
        "agent_identity": {
            "agent_runtime_id": agent_runtime_id,
            "agent_private_key": private_key_b64,
            "account_id": account_id,
            "chatgpt_user_id": user_id,
            "email": email,
            "plan_type": plan_type,
            "chatgpt_account_is_fedramp": False,
        },
    }
