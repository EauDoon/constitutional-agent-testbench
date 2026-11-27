"""Ed25519 signature verification (RFC 8032), standard library only.

Verification handles only public data, so a pure-Python implementation is
safe here: it has no secret to leak through timing. Signing needs a private
key and is never done in pure Python; see ``authorization.sign_authorization``.

The check matches OpenSSL's: ``S`` must be below the group order, the public
key must decode to a curve point, and ``[S]B - [k]A`` must encode to exactly
the ``R`` bytes in the signature, so a non-canonical ``R`` fails.
"""

from __future__ import annotations

import hashlib

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)

_Point = tuple[int, int, int, int]


def _add(left: _Point, right: _Point) -> _Point:
    x1, y1, z1, t1 = left
    x2, y2, z2, t2 = right
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = 2 * t1 * t2 * _D % _P
    d = 2 * z1 * z2 % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _multiply(scalar: int, point: _Point) -> _Point:
    result: _Point = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _encode(point: _Point) -> bytes:
    x, y, z, _t = point
    inverse = pow(z, _P - 2, _P)
    x, y = x * inverse % _P, y * inverse % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _decode(data: bytes) -> _Point | None:
    value = int.from_bytes(data, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


_BASE_Y = 4 * pow(5, _P - 2, _P) % _P
_BASE: _Point = (_recover_x(_BASE_Y, 0) or 0, _BASE_Y, 1,
                 (_recover_x(_BASE_Y, 0) or 0) * _BASE_Y % _P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Return True only for a valid Ed25519 signature of ``message``."""

    if len(public_key) != 32 or len(signature) != 64:
        return False
    point_a = _decode(public_key)
    if point_a is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(
        hashlib.sha512(signature[:32] + public_key + message).digest(), "little"
    ) % _L
    x, y, z, t = _multiply(k, point_a)
    negated: _Point = ((_P - x) % _P, y, z, (_P - t) % _P)
    return _encode(_add(_multiply(s, _BASE), negated)) == signature[:32]
