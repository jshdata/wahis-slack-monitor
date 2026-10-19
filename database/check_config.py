"""Check CI database configuration without logging credentials or connecting."""
from database.db import validate_database_settings, get_ssl_ca_path


def main():
    validate_database_settings()
    get_ssl_ca_path()
    print('Database settings and SSL CA path validated')


if __name__ == '__main__':
    main()
