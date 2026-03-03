from src.scripts.seed_permissions import seed_permissions
from src.scripts.create_default_role import create_default_roles
from src.scripts.create_first_superuser import create_first_superuser
from app.core.database import SessionLocal


def main():
    db = SessionLocal()
    try:
        seed_permissions(db)
        create_default_roles(db)
        create_first_superuser(db)
        print("Bootstrap completed successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
