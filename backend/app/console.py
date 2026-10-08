"""Couleurs ANSI pour les messages de statut dans le terminal (vert = OK, rouge = coupure)."""
_RESET = "\033[0m"


def green(text: str) -> str:
    return f"\033[32m{text}{_RESET}"


def red(text: str) -> str:
    return f"\033[31m{text}{_RESET}"
