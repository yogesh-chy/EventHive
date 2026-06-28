from django.db import migrations


class Migration(migrations.Migration):
    """
    Enable the pg_trgm PostgreSQL extension required by TrigramSimilarity
    in services/search.py. Without this, any search query that finds no
    full-text results will crash with:
      UndefinedFunction: function similarity(character varying, unknown) does not exist
    """

    dependencies = [
        ("events", "0002_event_search_vector_trigger"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql="DROP EXTENSION IF EXISTS pg_trgm;",
        ),
    ]
