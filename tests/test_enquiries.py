import json

from tests.conftest import signed_request


async def test_get_enquiry(cli, company, other_server):
    other_server.app['extra_attributes'] = 'default'
    r = await cli.get(cli.server.app.router['enquiry'].url_for(company=company.public_key))
    assert r.status == 200, await r.text()
    data = await r.json()
    assert len(data) == 2
    assert len(data['visible']) == 7
    assert data['visible'][0]['field'] == 'client_name'
    assert data['visible'][0]['max_length'] == 255
    date_field = next(f for f in data['visible'] if f['field'] == 'date-of-birth')
    assert date_field['label'] == 'Date of Birth'
    assert date_field['prefix'] == 'attributes'
    assert date_field['type'] == 'date'
    # once to get immediate response, once "on the worker"
    assert other_server.app['request_log'] == ['enquiry_options']

    r = await cli.get(cli.server.app.router['enquiry'].url_for(company=company.public_key))
    assert r.status == 200, await r.text()
    data = await r.json()
    assert len(data) == 2
    assert len(data['visible']) == 7
    # no more requests as data came from cache
    assert other_server.app['request_log'] == ['enquiry_options']


async def test_get_enquiry_repeat(cli, company, other_server, redis, worker):
    other_server.app['extra_attributes'] = 'default'
    r = await cli.get(cli.server.app.router['enquiry'].url_for(company=company.public_key))
    assert r.status == 200, await r.text()
    data = await r.json()
    assert len(data['visible']) == 7
    assert other_server.app['request_log'] == ['enquiry_options']

    r = await cli.get(cli.server.app.router['enquiry'].url_for(company=company.public_key))
    assert r.status == 200, await r.text()
    data = await r.json()
    assert len(data['visible']) == 7
    assert other_server.app['request_log'] == ['enquiry_options']

    raw_enquiry_options = await redis.get(b'enquiry-data-%d' % company.id)
    enquiry_options = json.loads(raw_enquiry_options)
    enquiry_options['last_updated'] -= 2000
    await redis.set(b'enquiry-data-%d' % company.id, json.dumps(enquiry_options).encode())

    r = await cli.get(cli.server.app.router['enquiry'].url_for(company=company.public_key))
    assert r.status == 200, await r.text()
    data = await r.json()
    assert len(data['visible']) == 7
    await worker.run_check()
    assert other_server.app['request_log'] == ['enquiry_options', 'enquiry_options']


async def test_post_enquiry_success(cli, company, other_server, worker):
    other_server.app['extra_attributes'] = 'default'
    data = {
        'client_name': 'Cat Flap',
        'client_phone': '123',
        'grecaptcha_response': 'good' * 5,
        'terms_and_conditions': True,
        'attributes': {
            'tell-us-about-yourself': 'hello',
            'how-did-you-hear-about-us': 'foo',
            'date-of-birth': 1969660800
        }
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers={'User-Agent': 'Testing Browser'})
    assert r.status == 201, await r.text()
    data = await r.json()
    assert data == {'status': 'enquiry submitted to TutorCruncher'}
    await worker.run_check()
    assert [
        'enquiry_options',
        (
            'grecaptcha_post',
            {
                'secret': 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
                'response': 'goodgoodgoodgoodgood',
            },
        ),
        (
            'enquiry_post',
            {
                'client_name': 'Cat Flap',
                'client_phone': '123',
                'user_agent': 'Testing Browser',
                'ip_address': None,
                'http_referrer': None,
                'terms_and_conditions': True,
                'attributes': {
                    'tell-us-about-yourself': 'hello',
                    'how-did-you-hear-about-us': 'foo',
                    'date-of-birth': '2032-06-01',
                },
            },
        ),
    ] == other_server.app['request_log']


async def test_post_enquiry_datetime(cli, company, other_server, worker):
    other_server.app['extra_attributes'] = 'datetime'
    data = {
        'client_name': 'Cat Flap',
        'grecaptcha_response': 'good' * 5,
        'attributes': {
            'date-field': '2032-06-01',
            'datetime-field': '2018-02-07T14:45',
        }
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers={'User-Agent': 'Testing Browser'})
    assert r.status == 201, await r.text()
    await worker.run_check()
    assert [
        'enquiry_options',
        (
            'grecaptcha_post',
            {
                'secret': 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
                'response': 'goodgoodgoodgoodgood',
            },
        ),
        (
            'enquiry_post',
            {
                'client_name': 'Cat Flap',
                'user_agent': 'Testing Browser',
                'ip_address': None,
                'http_referrer': None,
                'terms_and_conditions': False,
                'attributes': {
                    'date-field': '2032-06-01',
                    'datetime-field': '2018-02-07T14:45:00',
                },
            },

        ),
    ] == other_server.app['request_log']


async def test_post_enquiry_invalid_attributes(cli, company, other_server, worker):
    other_server.app['extra_attributes'] = 'default'
    data = {
        'client_name': 'Cat Flap',
        'client_phone': '123',
        'grecaptcha_response': 'good' * 5,
        'attributes': {
            'how-did-you-hear-about-us': 'spam',
            'date-of-birth': 'xxx'
        }
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers={'User-Agent': 'Testing Browser'})
    assert r.status == 400, await r.text()
    data = await r.json()
    await worker.run_check()
    assert data == {
        'details': [
            {
                'loc': ['tell-us-about-yourself'],
                'msg': 'field required',
                'type': 'value_error.missing',
            },
            {
                'ctx': {
                    'enum_values': ['', 'foo', 'bar', ],
                },
                'loc': ['how-did-you-hear-about-us'],
                'msg': "value is not a valid enumeration member; permitted: '', 'foo', 'bar'",
                'type': 'type_error.enum',
            },
            {
                'loc': ['date-of-birth'],
                'msg': 'invalid date format',
                'type': 'type_error.date',
            },
        ],
        'status': 'invalid attribute data',
    }


async def test_post_enquiry_bad_captcha(cli, company, other_server, worker):
    data = {
        'client_name': 'Cat Flap',
        'client_phone': '123',
        'grecaptcha_response': 'bad_' * 5,
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers={'X-Forwarded-For': '1.2.3.4'})
    assert r.status == 201, await r.text()
    await worker.run_check()
    assert other_server.app['request_log'] == [
        'enquiry_options',
        ('grecaptcha_post', {
            'secret': 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
            'response': 'bad_bad_bad_bad_bad_',
            'remoteip': '1.2.3.4'
        }),
    ]


async def test_post_enquiry_wrong_captcha_domain(cli, company, other_server, worker):
    data = {
        'client_name': 'Cat Flap',
        'client_phone': '123',
        'grecaptcha_response': 'good' * 5,
    }
    other_server.app['grecaptcha_host'] = 'other.com'
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers={'User-Agent': 'Testing Browser'})
    assert r.status == 201, await r.text()
    await worker.run_check()
    assert other_server.app['request_log'] == [
        'enquiry_options',
        ('grecaptcha_post', {
            'secret': 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
            'response': 'goodgoodgoodgoodgood'
        })
    ]


async def test_post_enquiry_400(cli, company, other_server, caplog, worker):

    other_server.app['extra_attributes'] = 'default'
    data = {
        'client_name': 'Cat Flap',
        'client_phone': '123',
        'grecaptcha_response': 'good' * 5,
        'attributes': {'tell-us-about-yourself': 'hello'},
    }
    headers = {
        'User-Agent': 'Testing Browser',
        'Origin': 'http://example.com',
        'Referer': 'http://cause400.com',
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers=headers)
    assert r.status == 201, await r.text()
    data = await r.json()
    await worker.run_check()
    assert data == {'status': 'enquiry submitted to TutorCruncher'}
    assert other_server.app['request_log'] == [
        'enquiry_options',
        (
            'grecaptcha_post',
            {
                'secret': 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
                'response': 'goodgoodgoodgoodgood',
            },
        ),
        (
            'enquiry_post',
            {
                'client_name': 'Cat Flap',
                'client_phone': '123',
                'user_agent': 'Testing Browser',
                'ip_address': None,
                'http_referrer': 'http://cause400.com',
                'attributes': {'tell-us-about-yourself': 'hello'},
                'terms_and_conditions': False,
            },
        ),
        'enquiry_options',
    ]
    assert '400 response posting to http://localhost:' in caplog.text


async def test_post_enquiry_skip_grecaptcha(cli, company, other_server, worker):
    data = {
        'client_name': 'Cat Flap',
        'upstream_http_referrer': 'foobar',
        'grecaptcha_response': 'mock-grecaptcha:{.private_key}'.format(company),
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers={'User-Agent': 'Testing Browser'})
    assert r.status == 201, await r.text()
    data = await r.json()
    assert data == {'status': 'enquiry submitted to TutorCruncher'}
    await worker.run_check()
    assert other_server.app['request_log'] == [
        'enquiry_options',
        (
            'enquiry_post',
            {
                'client_name': 'Cat Flap',
                'upstream_http_referrer': 'foobar',
                'user_agent': 'Testing Browser',
                'ip_address': None,
                'http_referrer': None,
                'terms_and_conditions': False,
            },
        ),
    ]


async def test_post_enquiry_500(cli, company, caplog, worker, redis):
    data = {
        'client_name': 'Cat Flap',
        'grecaptcha_response': 'good' * 5,
        'attributes': {'tell-us-about-yourself': 'hello'},
    }
    headers = {'Referer': 'http://snap.com', 'Origin': 'http://example.com'}
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers=headers)
    assert r.status == 201, await r.text()
    await worker.run_check()
    assert '500 response posting to http://localhost:' in caplog.text


async def test_post_enquiry_referrer_too_long(cli, company, other_server, worker):
    data = {
        'client_name': 'Cat Flap',
        'client_phone': '123',
        'grecaptcha_response': 'good' * 5,
        'upstream_http_referrer': 'X' * 2000,
        'attributes': {'tell-us-about-yourself': 'hello'},
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    headers = {'User-Agent': 'Testing Browser', 'Referer': 'Y' * 2000, 'Origin': 'http://example.com'}
    r = await cli.post(url, data=json.dumps(data), headers=headers)
    assert r.status == 201, await r.text()
    data = await r.json()
    assert data == {'status': 'enquiry submitted to TutorCruncher'}
    await worker.run_check()
    assert other_server.app['request_log'][2][1]['upstream_http_referrer'] == 'X' * 1023
    assert other_server.app['request_log'][2][1]['http_referrer'] == 'Y' * 1023


async def test_post_enquiry_referrer_blank(cli, company, other_server, worker):
    data = {
        'client_name': 'Cat Flap',
        'client_phone': '123',
        'grecaptcha_response': 'good' * 5,
        'upstream_http_referrer': '',
        'attributes': {'tell-us-about-yourself': 'hello'},
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    headers = {'User-Agent': 'Testing Browser', 'Origin': 'http://example.com'}
    r = await cli.post(url, data=json.dumps(data), headers=headers)
    assert r.status == 201, await r.text()
    data = await r.json()
    assert data == {'status': 'enquiry submitted to TutorCruncher'}
    await worker.run_check()
    assert other_server.app['request_log'][2][1]['upstream_http_referrer'] == ''


async def test_clear_enquiry_options(cli, company, redis):
    assert None is await redis.get(b'enquiry-data-%d' % company.id)

    r = await cli.get(cli.server.app.router['enquiry'].url_for(company=company.public_key))
    assert r.status == 200, await r.text()
    data = await r.json()
    assert len(data['visible']) == 4

    assert None is not await redis.get(b'enquiry-data-%d' % company.id)

    r = await signed_request(
        cli,
        cli.server.app.router['webhook-clear-enquiry'].url_for(company=company.public_key),
        signing_key_='this is the master key',
    )
    assert r.status == 200, await r.text()
    assert {'status': 'success', 'data_existed': True} == await r.json()

    assert None is await redis.get(b'enquiry-data-%d' % company.id)


async def test_clear_enquiry_options_no_data(cli, company, redis):
    assert None is await redis.get(b'enquiry-data-%d' % company.id)

    r = await signed_request(
        cli,
        cli.server.app.router['webhook-clear-enquiry'].url_for(company=company.public_key),
        signing_key_=company.private_key,
    )
    assert r.status == 200, await r.text()
    assert {'status': 'success', 'data_existed': False} == await r.json()

    assert None is await redis.get(b'enquiry-data-%d' % company.id)


async def test_clear_enquiry_options_invalid(cli, company, redis):
    r = await cli.get(cli.server.app.router['enquiry'].url_for(company=company.public_key))
    assert r.status == 200, await r.text()
    data = await r.json()
    assert len(data['visible']) == 4

    assert None is not await redis.get(b'enquiry-data-%d' % company.id)

    r = await signed_request(
        cli,
        cli.server.app.router['webhook-clear-enquiry'].url_for(company=company.public_key),
        signing_key_='this is wrong',
    )
    assert r.status == 401, await r.text()

    assert None is not await redis.get(b'enquiry-data-%d' % company.id)


async def test_post_all_optional(cli, company, other_server):
    other_server.app['extra_attributes'] = 'all_optional'
    data = {
        'client_name': 'Cat Flap',
        'client_phone': '123',
        'grecaptcha_response': 'good' * 5,
    }
    url = cli.server.app.router['enquiry'].url_for(company=company.public_key)
    r = await cli.post(url, data=json.dumps(data), headers={'User-Agent': 'Testing Browser'})
    assert r.status == 201, await r.text()
    data = await r.json()
    assert data == {'status': 'enquiry submitted to TutorCruncher'}
