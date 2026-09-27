"""웹 푸시에 쓸 VAPID 키쌍을 만들어 .env에 붙여넣을 형태로 출력한다."""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(raw: bytes) -> str:
    """입력: 바이트열, 출력: 패딩 없는 URL-safe base64 문자열."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def main() -> None:
    """입력 없음, 출력 없음; 새 키쌍을 만들어 환경변수 두 줄로 출력한다."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    print("아래 두 줄을 backend/.env 에 넣으세요. 공개키는 브라우저에 전달되고, 비밀키는 절대 공유하지 마세요.\n")
    print(f"VAPID_PUBLIC_KEY={_b64(public_raw)}")
    print(f"VAPID_PRIVATE_KEY={_b64(private_raw)}")


if __name__ == "__main__":
    main()
