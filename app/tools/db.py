import psycopg2 

import app.config as config 

def get_conn():
    return psycopg2.connect(config.DATABASE_URL)


