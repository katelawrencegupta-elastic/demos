"""Domain generation algorithms commonly seen in malware families."""

import hashlib
import random
import string
from datetime import datetime, timezone

CONSONANTS = "bcdfghjklmnpqrstvwxyz"
VOWELS = "aeiou"
TLDS = ("com", "net", "org", "biz", "info", "xyz", "top", "tk", "cc", "ru")

WORDLIST = (
    "table", "jacket", "door", "cloud", "river", "stone", "light", "storm",
    "pixel", "orbit", "delta", "crown", "flash", "ghost", "metal", "north",
    "south", "brave", "quick", "smart", "clean", "fresh", "happy", "lucky",
    "green", "black", "white", "silver", "golden", "crystal", "shadow", "magic",
)


def _random_tld() -> str:
    return random.choice(TLDS)


def random_domain(length: int | None = None) -> str:
    """High-entropy random alphanumeric subdomain."""
    size = length or random.randint(8, 16)
    label = "".join(random.choices(string.ascii_lowercase + string.digits, k=size))
    return f"{label}.{_random_tld()}"


def consonant_vowel_domain(length: int | None = None) -> str:
    """Alternating consonant/vowel pattern (e.g. naboperixo.com)."""
    size = length or random.randint(8, 14)
    chars = []
    for i in range(size):
        chars.append(random.choice(CONSONANTS if i % 2 == 0 else VOWELS))
    return f"{''.join(chars)}.{_random_tld()}"


def wordlist_domain(word_count: int | None = None) -> str:
    """Concatenated dictionary words (e.g. tablejacketdoor.net)."""
    count = word_count or random.randint(2, 4)
    label = "".join(random.choice(WORDLIST) for _ in range(count))
    return f"{label}.{_random_tld()}"


def time_seeded_domain(now: datetime | None = None) -> str:
    """Date/hour-seeded label (e.g. ajf8293k2025060914.tk)."""
    now = now or datetime.now(timezone.utc)
    seed = now.strftime("%Y%m%d%H")
    prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(4, 8)))
    return f"{prefix}{seed}.{_random_tld()}"


def hex_seed_domain(seed: str | None = None) -> str:
    """Hex-encoded seed label (e.g. a3f2b891c4.org)."""
    if seed is None:
        seed = str(random.randint(0, 2**32 - 1))
    digest = hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest()
    label = digest[: random.randint(10, 14)]
    return f"{label}.{_random_tld()}"


ALGORITHMS = {
    "random": random_domain,
    "consonant_vowel": consonant_vowel_domain,
    "wordlist": wordlist_domain,
    "time_seeded": time_seeded_domain,
    "hex_seed": hex_seed_domain,
}


def generate_domain(algorithm: str | None = None) -> tuple[str, str]:
    """Return (domain, algorithm_name)."""
    name = algorithm or random.choice(list(ALGORITHMS))
    if name not in ALGORITHMS:
        name = "random"
    return ALGORITHMS[name](), name
