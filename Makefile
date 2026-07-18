.PHONY: up seed test lint logs

up:
	docker-compose up --build

seed:
	docker-compose exec api python manage.py seed_data

test:
	docker-compose exec api pytest
	docker-compose exec web npm test

lint:
	docker-compose exec web npm run lint

logs:
	docker-compose logs -f
