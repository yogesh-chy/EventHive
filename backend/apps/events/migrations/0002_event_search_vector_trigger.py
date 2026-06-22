from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION eventhive_events_search_vector_update()
            RETURNS trigger AS $$
            BEGIN
                NEW.search_vector :=
                    setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
                    setweight(to_tsvector('english', coalesce(NEW.venue, '')), 'C') ||
                    setweight(to_tsvector('english', coalesce(NEW.city, '')), 'C');
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS events_search_vector_update ON events_event;
            CREATE TRIGGER events_search_vector_update
            BEFORE INSERT OR UPDATE OF title, description, venue, city
            ON events_event
            FOR EACH ROW
            EXECUTE FUNCTION eventhive_events_search_vector_update();

            UPDATE events_event
            SET search_vector =
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(description, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(venue, '')), 'C') ||
                setweight(to_tsvector('english', coalesce(city, '')), 'C');
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS events_search_vector_update ON events_event;
            DROP FUNCTION IF EXISTS eventhive_events_search_vector_update();
            """,
        ),
    ]
