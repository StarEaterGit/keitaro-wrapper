from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.config import get_settings

class Base(DeclarativeBase):
    pass

_engine = None
_Factory = None

def factory():
    global _engine, _Factory
    if _Factory is None:
        url = get_settings().database_url
        _engine = create_engine(url, pool_pre_ping=True, connect_args={'check_same_thread': False} if url.startswith('sqlite:') else {})
        _Factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _Factory

def get_db() -> Iterator[Session]:
    with factory()() as session:
        yield session
