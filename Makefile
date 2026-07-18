.PHONY: up seed test logs

up:
	docker-compose up --build

seed:
	docker-compose exec api python manage.py seed_data

test:
	docker-compose exec api pytest

logs:
	docker-compose logs -f
