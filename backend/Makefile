build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

migrate:
	docker-compose exec web python manage.py migrate

migrations:
	docker-compose exec web python manage.py makemigrations

superuser:
	docker-compose exec web python manage.py createsuperuser

shell:
	docker-compose exec web python manage.py shell

test:
	docker-compose exec web pytest

logs:
	docker-compose logs -f
