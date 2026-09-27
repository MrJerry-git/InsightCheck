"""口令与会话令牌的安全工具。

只用标准库实现：PBKDF2-HMAC-SHA256 派生口令，SHA-256 保存会话令牌摘要，
比较使用 hmac.compare_digest，避免明文落库与时间侧信道。
"""

import hashlib
import hmac
import secrets
import string

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 200
SALT_BYTES = 16
TOKEN_BYTES = 32
DEFAULT_ITERATIONS = 210_000


class WeakPasswordError(ValueError):
    """口令不满足最低强度要求。"""


def validate_password_strength(password: str) -> None:
    """口令规则：10—200 字符，且至少包含两类字符，不接受全同字符。"""

    if len(password) < PASSWORD_MIN_LENGTH:
        raise WeakPasswordError(f"口令至少 {PASSWORD_MIN_LENGTH} 个字符")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise WeakPasswordError(f"口令最多 {PASSWORD_MAX_LENGTH} 个字符")
    if len(set(password)) < 3:
        raise WeakPasswordError("口令不能是重复字符或过于简单的组合")
    classes = sum(
        bool(chars & set(password))
        for chars in (
            set(string.ascii_lowercase),
            set(string.ascii_uppercase),
            set(string.digits),
            set(string.punctuation) | set("！＃￥％…（）*+，-。／：；＜＝＞？＠【】"),
        )
    )
    if classes < 2:
        raise WeakPasswordError("口令需同时包含字母、数字或符号中的至少两类")


def hash_password(
    password: str,
    *,
    salt: str | None = None,
    iterations: int = DEFAULT_ITERATIONS,
) -> tuple[str, str, int]:
    """返回 (口令摘要, 盐值, 迭代次数)。参数可传入以支持日后重算与升级。"""

    validate_password_strength(password)
    resolved_salt = salt or secrets.token_hex(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        resolved_salt.encode("utf-8"),
        iterations,
    )
    return digest.hex(), resolved_salt, iterations


def verify_password(
    password: str,
    *,
    password_hash: str,
    salt: str,
    iterations: int,
) -> bool:
    """常量时间比较口令；空口令或参数缺失直接判定失败。"""

    if not password or not password_hash or not salt or iterations <= 0:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate, password_hash)


def generate_session_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """会话令牌只保存摘要，数据库泄露不能直接换取登录态。"""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
