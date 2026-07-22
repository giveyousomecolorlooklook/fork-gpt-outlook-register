#!/usr/bin/env python3
"""
跳过接码，从已有 access_token / session_token 获取 refresh_token。

参考 fork-gpt-Codex-Agent-Identity 项目：用已有 access_token 跳过 SMS/OTP
流程，通过 Codex OAuth 直连换取 refresh_token。

用法：
    python get_refresh_token.py --access-token "eyJhbGci..."
    python get_refresh_token.py --file session.json
    python get_refresh_token.py --session-token "xxx"

输出：
    保存 account_{email}_rt.json，包含 email / access_token / refresh_token。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import Config
from auth_flow import AuthFlow

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="跳过接码，用已有凭证换 refresh_token",
    )
    parser.add_argument(
        "--access-token", type=str, default="",
        help="ChatGPT session JWT (accessToken)",
    )
    parser.add_argument(
        "--session-token", type=str, default="",
        help="__Secure-next-auth.session-token cookie 值",
    )
    parser.add_argument(
        "--file", "-f", type=str, default="",
        help="包含 accessToken 的 JSON 文件路径",
    )
    parser.add_argument(
        "--output", "-o", type=str, default="",
        help="输出 JSON 文件路径",
    )
    parser.add_argument(
        "--proxy", "-p", type=str, default="",
        help="出口代理 URL",
    )
    parser.add_argument(
        "--device-id", type=str, default="",
        help="设备 ID（留空自动生成）",
    )
    parser.add_argument(
        "--allow-retry", action="store_true",
        help="Codex RT 交换失败时允许重试",
    )
    parser.add_argument(
        "--secondary-exchange", action="store_true",
        help="主流程失败时尝试二级 OAuth 交换",
    )
    args = parser.parse_args(argv)

    access_token = (args.access_token or "").strip()
    session_token = (args.session_token or "").strip()
    device_id = (args.device_id or "").strip() or str(uuid.uuid4())

    if args.file and not access_token:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                access_token = (
                    data.get("accessToken")
                    or data.get("access_token")
                    or ""
                )
                if not isinstance(access_token, str):
                    access_token = ""
                if not session_token:
                    session_token = (
                        data.get("session_token")
                        or data.get("sessionToken")
                        or ""
                    ).strip()
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"错误：无法读取文件 {args.file}: {e}", file=sys.stderr)
            return 1

    if not access_token and not session_token:
        print("错误：需要 --access-token 或 --session-token 或 --file",
              file=sys.stderr)
        parser.print_help()
        return 1

    if access_token:
        print(f"access_token 长度: {len(access_token)}")
    if session_token:
        print(f"session_token 长度: {len(session_token)}")

    os.environ["OAUTH_CODEX_RT_EXCHANGE"] = "1"
    os.environ["OAUTH_CODEX_RT_ALLOW_RETRY"] = "1" if args.allow_retry else "0"
    if args.secondary_exchange:
        os.environ["OAUTH_SECONDARY_AUTHORIZE_EXCHANGE"] = "1"
    os.environ["SKIP_OAUTH_TOKEN_EXCHANGE"] = "1"
    os.environ["OAUTH_TOKEN_EXCHANGE_FROM_CALLBACK"] = "0"
    os.environ["OAUTH_EXCHANGE_BEFORE_CALLBACK"] = "0"

    proxy = args.proxy or os.environ.get("PROXY") or None

    cfg = Config()
    cfg.proxy = proxy

    flow = AuthFlow(cfg)
    logger.info("初始化已有凭证 (跳过 SMS/OTP 注册) ...")

    try:
        flow.from_existing_credentials(
            session_token=session_token,
            access_token=access_token,
            device_id=device_id,
        )
    except Exception as e:
        logger.error(f"凭证初始化失败: {e}")
        return 1

    email = flow.result.email or "unknown"
    if not email and access_token and access_token.count(".") >= 2:
        import base64 as _b64
        try:
            payload_b64 = access_token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(
                _b64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
            )
            profile = payload.get("https://api.openai.com/profile", {})
            email = (profile.get("email") or payload.get("email") or "unknown")
            flow.result.email = email
        except Exception:
            pass

    logger.info(f"账号: {email}")

    logger.info("开始 Codex OAuth 直连换取 refresh_token ...")
    ok = flow.oauth_codex_rt_exchange(mail_provider=None)
    if not ok:
        logger.warning("Codex OAuth 主流程未拿到 refresh_token")

    if not flow.result.refresh_token and args.secondary_exchange:
        logger.info("尝试二级 OAuth 交换 ...")
        try:
            flow.oauth_secondary_authorize_exchange()
        except Exception as e:
            logger.warning(f"二级交换异常: {e}")

    try:
        flow.get_auth_session()
    except Exception as e:
        logger.warning(f"刷新 session 失败: {e}")

    d = flow.result.to_dict()
    logger.info(
        f"完成: access_token_len={len(d.get('access_token') or '')} "
        f"refresh_token_len={len(d.get('refresh_token') or '')} "
        f"session_token_len={len(d.get('session_token') or '')}"
    )

    if not d.get("refresh_token"):
        print("\n⚠️ 未获取到 refresh_token", file=sys.stderr)
        if d.get("access_token"):
            print("   但有 access_token 可用", file=sys.stderr)
        return 1

    safe_email = (email or "unknown").replace("@", "_at_")
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = ROOT / f"account_{safe_email}_rt.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

    print(f"\n=== DONE ===")
    print(f"refresh_token 已保存到: {out_path}")
    print(f"email: {d.get('email')}")
    print(f"refresh_token len: {len(d.get('refresh_token') or '')}")
    print(f"access_token len:  {len(d.get('access_token') or '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())