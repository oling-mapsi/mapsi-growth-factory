from app.infrastructure.db.models import RepositorySourceModel


def ensure_repository_source(session, source_id: str, full_name: str):
    if session.get(RepositorySourceModel, source_id) is None:
        session.add(RepositorySourceModel(id=source_id, full_name=full_name, installation_id='synthetic-installation'))
        session.flush()
