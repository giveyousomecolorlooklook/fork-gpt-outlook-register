#!/usr/bin/env python3
"""WebUI 一键启动脚本（从 .env 文件读取账号密码）"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import webbrowser
from pathlib import Path

# Windows 控制台 GBK 编码兼容
if sys.platform.startswith("win"):
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent


def main():
    # 确保基础依赖 & python-dotenv 已安装
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        from dotenv import load_dotenv
    except ImportError:
        print("[!] 缺少依赖，正在安装 fastapi / uvicorn / python-dotenv ...")
        import subprocess
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "fastapi", "uvicorn[standard]", "pydantic>=2", "python-dotenv",
        ])
        from dotenv import load_dotenv

    # 加载 .env 环境变量文件
    load_dotenv(ROOT / ".env")

    # 从环境变量中读取用户名密码，若不存在则降级为默认值
    env_username = os.getenv("WEBUI_USERNAME", "admin")
    env_password = os.getenv("WEBUI_PASSWORD", "123456")

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8765, help="监听端口 (默认 8765)")
    ap.add_argument("--username", default=env_username, help="登录用户名 (默认优先读取 .env)")
    ap.add_argument("--password", default=env_password, help="登录密码 (默认优先读取 .env)")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--reload", action="store_true", help="开发模式 (代码改动自动重启)")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    import uvicorn
    from fastapi import Request, Response
    from fastapi.security import HTTPBasic, HTTPBasicCredentials
    from webui.app import app as original_app

    # 注入 HTTP Basic 认证中间件
    security = HTTPBasic()

    @original_app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        try:
            credentials: HTTPBasicCredentials = await security(request)
            is_user_correct = secrets.compare_digest(credentials.username, args.username)
            is_pass_correct = secrets.compare_digest(credentials.password, args.password)
            
            if is_user_correct and is_pass_correct:
                return await call_next(request)
        except Exception:
            pass

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="WebUI Authorization"'},
        )

    # 启动服务
    url = f"http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{args.port}/"
    print(f"\n🔔 团子喵 WebUI 启动中...")
    print(f"   访问地址: {url}")
    print(f"   🔑 当前账号: {args.username}\n")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run(
        original_app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()