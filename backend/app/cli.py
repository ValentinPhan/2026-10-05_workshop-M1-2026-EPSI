"""Gestion des comptes en ligne de commande (récupération si le mot de passe admin est perdu).

  python -m app.cli list
  python -m app.cli create <identifiant> <admin|agent>     (le mot de passe est demandé, non affiché)
  python -m app.cli passwd <identifiant>                    (nouveau mot de passe ; ferme les sessions ouvertes)

À lancer depuis backend/, avec le venv, et la même DATABASE_URL que l'API.
"""
import getpass
import sys

from .auth import MIN_PASSWORD_LENGTH, ROLES, USERNAME_RE, hash_password
from .db import database


def ask_password() -> str:
    password = getpass.getpass("Mot de passe : ")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Mot de passe : {MIN_PASSWORD_LENGTH} caractères minimum")
    if password != getpass.getpass("Confirmer : "):
        sys.exit("Les mots de passe diffèrent")
    return password


def main(argv: list[str]) -> None:
    database.init()
    command = argv[1] if len(argv) > 1 else ""
    if command == "list":
        for u in database.list_users():
            print(f"#{u['id']:<3} {u['username']:<20} {u['role']}")
    elif command == "create" and len(argv) == 4:
        username, role = argv[2], argv[3]
        if not USERNAME_RE.match(username) or role not in ROLES:
            sys.exit(f"Identifiant : 3 à 32 caractères (lettres, chiffres, _ . -) ; rôle : {' | '.join(ROLES)}")
        if database.create_user(username, hash_password(ask_password()), role) is None:
            sys.exit("Cet identifiant existe déjà")
        database.audit(None, "cli_user_create", f"{username} ({role})")
        print(f"compte « {username} » ({role}) créé")
    elif command == "passwd" and len(argv) == 3:
        user = database.get_user_by_name(argv[2])
        if user is None:
            sys.exit("Utilisateur introuvable")
        database.set_password(user["id"], hash_password(ask_password()))
        database.audit(None, "cli_password_reset", user["username"])
        print("mot de passe modifié, sessions ouvertes fermées")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv)
