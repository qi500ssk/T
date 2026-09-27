from types import SimpleNamespace


def test_retrieval_response_keeps_job_snapshot(monkeypatch):
    from apps.api import retrieval_settings as api
    values = dict(embedding_provider='mock', embedding_model='mock', embedding_dim=3,
                  embedding_base_url='', embedding_api_key='', embedding_request_dimensions=False,
                  embedding_model_path='', embedding_query_instruction='')
    job = {'status': 'indexing', 'processed': 0, 'total': 1}
    state = SimpleNamespace(runtime_settings_store=SimpleNamespace(snapshot=lambda: {'embedding': values}),
                            embedding_provider=SimpleNamespace(model_name='mock', dimension=3), retrieval_job=job)
    def finish_during_status(model):
        job['status'] = 'completed'
        state.embedding_provider = SimpleNamespace(model_name='keyword-v1', dimension=0)
        return None
    monkeypatch.setattr(api, 'cached_model_directory', finish_during_status)
    result = api.public_status(SimpleNamespace(app=SimpleNamespace(state=state)))
    assert result['job']['status'] == 'indexing'
    assert result['semantic_ready'] is True
    assert job['status'] == 'completed'
