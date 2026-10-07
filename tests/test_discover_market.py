import copy
import hashlib
import time
from unittest.mock import patch

import pytest

from workbench.db import Store
from workbench.sources import SourcesService, TRENDING_URL, LEADERBOARD_URLS


@pytest.fixture
def service(tmp_path):
    with patch.object(SourcesService, '_refresh_agents'), patch.object(SourcesService, '_local_metrics', return_value={}):
        value = SourcesService(Store(tmp_path / 'test.sqlite3'), tmp_path, task_root=tmp_path, start_background=False)
    yield value
    value.close()


def repository(name='owner/repo', gain=125):
    return {'repository': name, 'title': name, 'summary': 'A useful AI project',
            'url': 'https://github.com/' + name, 'language': 'Python', 'total_stars': 1000,
            'stars_today': gain, 'trending_rank': 1, 'growth_window': 'today'}


def allow(service, key):
    value = service._get(key + '.http', {})
    value['next_allowed'] = 0
    service._set(key + '.http', value)


def test_trending_fixed_source_cache_and_snapshot_after_eviction(service):
    with patch('workbench.trending.parse_trending', return_value=[repository()]), \
            patch.object(service, '_request', return_value=(200, b'<html/>', {'Content-Type': 'text/html', 'ETag': 'v1'})) as request:
        service.refresh('trending')
        service.refresh('trending')
        request.assert_called_once_with(TRENDING_URL, {'Accept': 'text/html'}, timeout=7)
    view = service.discover()
    item = view['items'][0]
    assert view['trending']['item_ids'] == [item['id']]
    assert item['stars_today'] == 125
    assert item['id'] == 'github:' + hashlib.sha256(item['url'].lower().encode()).hexdigest()[:20]
    service.discover_meta(item['id'], {'bookmarked': True, 'trial_status': '想试用'})
    service.store.set('relations', [{'from_type': 'discover', 'from_id': item['id'], 'to_type': 'task', 'to_id': 'x'}])
    allow(service, 'discover.trending')
    with patch('workbench.trending.parse_trending', return_value=[repository('owner/new', 300)]), \
            patch.object(service, '_request', return_value=(200, b'<html/>', {})):
        service.refresh('trending')
    saved = next(x for x in service.discover()['items'] if x['id'] == item['id'])
    assert saved['bookmarked'] and saved['trial_status'] == '想试用'
    assert saved['stars_today'] == 125 and saved['outside_current_window']
    assert item['id'] not in service.discover()['trending']['item_ids']
    with patch.object(service, '_request', side_effect=AssertionError('getter must not fetch')):
        assert service.discover()['trending']['status'] == 'ready'


def test_trending_preserves_personal_identity_and_manual_project(service):
    manual = dict(repository('OWNER/Repo'), id='original-id', kind='project', license='MIT',
                  bookmarked=False, trial_status=None)
    service._set('discover.projects', [manual, dict(manual, id='other', url='https://github.com/other/project')])
    service._set('discover.meta', {'original-id': {'bookmarked': True, 'trial_status': '试用中'}})
    with patch('workbench.trending.parse_trending', return_value=[repository()]), \
            patch.object(service, '_request', return_value=(200, b'<html/>', {})):
        service.refresh('trending')
    view = service.discover()
    assert len(view['items']) == 2
    assert view['trending']['item_ids'] == ['original-id']
    current = next(x for x in view['items'] if x['id'] == 'original-id')
    assert current['bookmarked'] and current['trial_status'] == '试用中'
    assert current['stars_today'] == 125
    assert current['license'] == 'MIT'
    assert service._get('discover.projects', []) == [manual, dict(manual, id='other', url='https://github.com/other/project')]


def test_html_failure_304_rate_limit_preserve_snapshot(service):
    key = 'discover.trending'
    with patch('workbench.trending.parse_trending', return_value=[repository()]), \
            patch.object(service, '_request', return_value=(200, b'<html/>', {'ETag': 'v1'})):
        service.refresh('trending')
    baseline = copy.deepcopy(service.discover()['items'])
    original_update = service.discover()['trending']['updated_at']
    allow(service, key)
    with patch.object(service, '_request', return_value=(304, None, {'Cache-Control': 'max-age=90'})) as request:
        service.refresh('trending')
        assert request.call_args.args[1]['If-None-Match'] == 'v1'
    assert service.discover()['trending']['updated_at'] == original_update
    assert service._get(key + '.http', {})['next_allowed'] - time.time() > 1790
    allow(service, key)
    with patch('workbench.trending.parse_trending', side_effect=ValueError('format changed')), \
            patch.object(service, '_request', return_value=(200, b'<html/>', {})):
        service.refresh('trending')
    assert service.discover()['trending']['status'] == 'unavailable'
    assert service.discover()['trending']['stale']
    assert service.discover()['items'] == baseline
    allow(service, key)
    with patch.object(service, '_request', return_value=(429, None, {'Retry-After': '600'})) as request:
        service.refresh('trending')
        service.refresh('trending')
        assert request.call_count == 1
    assert service.discover()['trending']['status'] == 'rate_limited'
    assert service.discover()['items'] == baseline
    assert service._get(key + '.http', {})['next_allowed'] - time.time() > 590


def test_leaderboards_categories_isolated_and_refresh_has_fixed_urls(service):
    parsed = {'items': [{'rank': 1, 'name': 'A', 'vendor': 'V', 'score': 70.2, 'input_price': None}],
              'source_updated_label': '10/07 14:06', 'evaluation_count': 35,
              'organization_count': 7, 'price_unit': '人民币 / 百万 Token'}
    def response(url, headers, timeout):
        assert url in LEADERBOARD_URLS.values()
        assert headers == {'Accept': 'text/html'}
        return 200, b'<html/>', {'Content-Type': 'text/html', 'Cache-Control': 'max-age=299'}
    with patch('workbench.leaderboard.parse_leaderboard', return_value=parsed), \
            patch.object(service, '_request', side_effect=response) as request:
        service.refresh('leaderboards')
        service.refresh('leaderboards')
        assert request.call_count == 5
    categories = service.discover()['leaderboards']['categories']
    assert set(categories) == set(LEADERBOARD_URLS)
    assert all(c['items'][0]['score'] == 70.2 for c in categories.values())
    original = copy.deepcopy(categories['coding'])
    allow(service, 'discover.leaderboards.overall')
    with patch.object(service, '_request', return_value=(503, None, {'Retry-After': '120'})) as request:
        service.refresh('leaderboards')
        request.assert_called_once()
    categories = service.discover()['leaderboards']['categories']
    assert categories['coding'] == original
    assert categories['overall']['status'] == 'unavailable' and categories['overall']['stale']
    assert categories['overall']['items'] == parsed['items']


def test_unsolicited_304_and_non_html_do_not_create_ready_collection(service):
    with patch.object(service, '_request', return_value=(304, None, {})):
        service.refresh('trending')
    assert service.discover()['trending']['status'] == 'unavailable'
    allow(service, 'discover.trending')
    with patch.object(service, '_request', return_value=(200, b'{"items":[]}', {'Content-Type': 'application/json'})):
        service.refresh('trending')
    assert service.discover()['trending']['item_ids'] == []
    assert service.discover()['trending']['status'] == 'unavailable'


@pytest.mark.parametrize('manual_record', [False, True])
def test_legacy_alias_keeps_latest_growth_when_project_leaves_daily_list(service, manual_record):
    def refresh(name='owner/repo', gain=125):
        allow(service, 'discover.trending')
        with patch('workbench.trending.parse_trending', return_value=[repository(name, gain)]), \
                patch.object(service, '_request', return_value=(200, b'<html/>', {})):
            service.refresh('trending')

    refresh()
    source_id = service.discover()['items'][0]['id']
    legacy_id = 'legacy-aihot-or-manual'
    legacy = dict(repository(gain=50), id=legacy_id, kind='project', bookmarked=True,
                  trial_status=None, source_item_id=source_id, fetched_at='2026-01-01T00:00:00+08:00')
    service._set('discover.saved', {legacy_id: legacy})
    service._set('discover.meta', {legacy_id: {'bookmarked': True}})
    if manual_record:
        service._set('discover.projects', [legacy])
    current = service.discover()['items'][0]
    assert current['id'] == legacy_id and source_id in current['alias_ids']
    assert current['stars_today'] == 125

    refresh(gain=300)
    current = service.discover()['items'][0]
    assert current['id'] == legacy_id and current['stars_today'] == 300
    assert service._get('discover.saved', {})[legacy_id]['stars_today'] == 300
    refresh('owner/new', 400)
    outside = next(x for x in service.discover()['items'] if x['id'] == legacy_id)
    assert outside['stars_today'] == 300 and outside['outside_current_window']
    assert source_id in outside['alias_ids']
    assert service.preserve_discovery(source_id)['id'] == source_id
    service.discover_meta(source_id, {'bookmarked': False, 'trial_status': None})
    assert not any(x.get('bookmarked') for x in service.discover()['items'] if x['url'] == legacy['url'])
    if manual_record:
        assert service._get('discover.projects', []) == [legacy]


def test_referenced_identity_unions_personal_state_and_alias_actions_share_updates(service):
    source_id = 'github:' + hashlib.sha256(b'https://github.com/owner/repo').hexdigest()[:20]
    manual_id, news_id = 'original-manual-id', 'aihot:42'
    manual = dict(repository(), id=manual_id, kind='project', license='MIT', bookmarked=True, trial_status=None)
    news = dict(repository(), id=news_id, kind='project', bookmarked=False, trial_status='想试用')
    service._set('discover.projects', [manual])
    service._set('discover.cache', {'items': [news], 'status': 'ready'})
    service._set('discover.meta', {manual_id: {'bookmarked': True}, news_id: {'trial_status': '想试用'}})
    service.store.set('relations', [{'from_type': 'discover', 'from_id': source_id, 'to_type': 'task', 'to_id': 'x'}])
    with patch('workbench.trending.parse_trending', return_value=[repository(gain=300)]), \
            patch.object(service, '_request', return_value=(200, b'<html/>', {})):
        service.refresh('trending')
    item = service.discover()['items'][0]
    assert item['id'] == source_id
    assert item['bookmarked'] and item['trial_status'] == '想试用'
    assert set(item['alias_ids']) == {manual_id, news_id}
    assert service.discover()['trending']['item_ids'] == [source_id]
    assert item['license'] == 'MIT'

    # A relation may still use any historical identity after URL de-duplication.
    assert service.preserve_discovery(news_id)['id'] == news_id
    assert service._get('discover.saved', {})[news_id]['id'] == news_id
    service.discover_meta(news_id, {'bookmarked': False, 'trial_status': None})
    item = service.discover()['items'][0]
    assert item['id'] == source_id and not item['bookmarked'] and item['trial_status'] is None
    for identity in (source_id, manual_id, news_id):
        assert not service._get('discover.meta', {})[identity]['bookmarked']
        assert service._get('discover.meta', {})[identity]['trial_status'] is None
    # Adding a star through another alias retains the referenced primary.
    service.discover_meta(manual_id, {'bookmarked': True})
    assert service.discover()['items'][0]['id'] == source_id
    assert service.discover()['items'][0]['bookmarked']
    service.discover_meta(source_id, {'bookmarked': False})
    assert not service.discover()['items'][0]['bookmarked']
    assert service._get('discover.projects', []) == [manual]
