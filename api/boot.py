"""启动辅助模块: 回环检测 / API token 读取与生成 (SEC-03, D-03/D-04/D-05)。

boot 序列中的纯函数层: 每个函数只依赖显式传入的路径参数与环境变量,
不计算路径常量、不做控制台输出 (D-05 的单句提示约束统一由 api/main.py 保证)。

顺序约定 (Pitfall 2): 非回环分支只评估"是否已配置 token"(env 优先, 文件其次),
绝不在此分支生成 token —— 否则 SEC-03 的拒绝逻辑将永远不可达。
"""
import ipaddress
import os
import secrets


def is_loopback(host: str) -> bool:
    """host 是否为回环地址。

    bare "localhost"(不区分大小写) 直接判定为回环; 其余交给
    ipaddress.ip_address(host).is_loopback (覆盖 127.0.0.0/8 与 ::1)。
    无法解析的字符串(含空串)按 fail-closed 返回 False —— 视为非回环,
    从而触发 token 要求。禁止字符串前缀检查 (host.startswith("127."))。
    """
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read_token(token_path: str):
    """读取 token: GOGO_API_TOKEN 环境变量优先, 文件其次 (D-04, 同 tushare 惯例)。

    环境值先 strip, 非空才生效; 文件以 utf-8 读取并 strip。
    空环境值 / 空文件 / 文件读取失败均视为"无 token" (返回 None)。
    """
    tok = os.environ.get("GOGO_API_TOKEN", "").strip()
    if tok:
        return tok
    if os.path.exists(token_path):
        try:
            with open(token_path, encoding="utf-8") as f:
                tok = f.read().strip()
                if tok:
                    return tok
        except Exception:
            pass
    return None


def has_token(token_path: str) -> bool:
    """是否已配置 token (env 优先, 文件其次)。"""
    return read_token(token_path) is not None


def ensure_token(token_path: str) -> str:
    """确保 token 文件存在 (D-03)。

    文件已存在 -> 返回其 strip 后的内容, 不打印任何东西;
    否则用 secrets.token_urlsafe(32) 生成 (绝不用 random/uuid4),
    必要时创建父目录, 以 utf-8 单行写入, 返回该 token。
    本函数永不打印 (D-05)。
    """
    if os.path.exists(token_path):
        try:
            with open(token_path, encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass
    token = secrets.token_urlsafe(32)
    parent = os.path.dirname(token_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    return token
