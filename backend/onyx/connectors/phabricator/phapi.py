#!/usr/bin/env -S uv run --script

# Phabricator API wrapper
# (C) 2025 Thinkst Applied Research, PTY
# Author: jacob@thinkst.com

import requests, math

def get_user_by_phid(phid : str | None, api_base, api_token) -> str | None:
    '''
    Returns username based on the passed PHID, or None if it's not found
    '''
    if phid is None:
        return None
    q = {
        'api.token': api_token,
        'constraints[phids][]': phid, # This is hideous
        'limit': 1
    }
    res = requests.get(api_base + 'user.search', data=q)
    if res.status_code != 200:
        print(f'Error: {res.text}')
        return None
    rjson = res.json()
    if len(rjson['result']['data']) == 0:
        return None
    return rjson['result']['data'][0]['fields']['username']

def get_maniphest_tickets(limit : int, api_base, api_token, start = None, end = None) -> list[dict[str, str]]:
    '''
    Returns a list of the tickets as a dict with the following keys:
    - title: Ticket title
    - PHID: Document PHID
    - owner: Username of the ticket owner/assignee
    - author: Username of the ticket author
    - status: Ticket status
    - tid: Ticket ID (e.g. T123)
    - description: Ticket description
    - priority: Ticket priority
    - date_modified: When the ticket was last edited
    '''
    def _mp_to_ticket(ph_res : dict[str, str | int]) -> dict[str, str | int]:
        '''
        Parses out the specific information from a Phab doc into the format needed for parsing
        '''
        return {
            'title': ph_res['fields']['name'],
            'tid': 'T' + str(ph_res['id']),
            'PHID': ph_res['phid'],
            'description': ph_res['fields']['description']['raw'],
            'status': ph_res['fields']['status']['value'],
            'owner': get_user_by_phid(ph_res['fields']['ownerPHID'], api_base, api_token),
            'author': get_user_by_phid(ph_res['fields']['authorPHID'], api_base, api_token),
            'priority': ph_res['fields']['priority']['name'],
            'date_modified': ph_res['fields']['dateModified']
        }

    tickets = []
    phab_data = []
    q : dict[str, str | int] = {
        'api.token': api_token,
        'order': 'newest',
    }
    if limit == -1 or limit > 100:
        q['limit'] = 1
        res = requests.get(api_base + 'maniphest.search', data=q)
        if res.status_code != 200:
            print(f'ERROR: {res.text}')
            return []
        num_tts = res.json()['result']['data'][0]['id']
        print(f'Highest TT# {num_tts}')
        q['limit'] = 100
        if limit != -1:
            limit = min(num_tts, limit)
            num_calls = math.ceil(limit / 100) # The Phab API only allows 100 at most
            rem = limit % 100
            for _ in range(num_calls - 1):
                res = requests.get(api_base + 'maniphest.search', data=q)
                if res.status_code != 200:
                    print(f'ERROR: {res.text}')
                    return []
                rjson = res.json()
                if rjson is None:
                    continue
                phab_data += rjson.get('result', {}).get('data', [])
                if rjson['result']['cursor']['after'] is None:
                    break
                q['after'] = rjson['result']['cursor']['after']
            q['limit'] = rem
            res = requests.get(api_base + 'maniphest.search', data=q)
            if res.status_code != 200:
                print(f'ERROR: {res.text}')
                return []
            rjson = res.json()
            if not rjson is None:
                phab_data += rjson.get('result', {}).get('data', [])
        else: # Get all the docs
            limit = num_tts
            while True:
                q['limit'] = 100
                res = requests.get(api_base + 'maniphest.search', data=q)
                if res.status_code != 200:
                    print(f'ERROR: {res.text}')
                    return []
                rjson = res.json()
                if rjson is None:
                    continue
                phab_data += rjson['result']['data']
                if rjson['result']['cursor']['after'] is None:
                    break
                q['after'] = rjson['result']['cursor']['after']
    else:
        q['limit'] = limit
        res = requests.get(api_base + 'maniphest.search', data=q)
        if res.status_code != 200:
            print(f'ERROR: {res.text}')
            return []
        rjson = res.json()
        if rjson is None:
            return []
        phab_data = rjson['result']['data']

    for t in phab_data:
        if start is not None and t['fields']['dateModified'] < start:
            continue
        if end is not None and t['fields']['dateModified'] > end:
            continue
        ticket = _mp_to_ticket(t)
        if len([e for e in tickets if ticket['tid'] == e['tid']]) == 0: # Since every version is treated as a different document/object
            tickets.append(ticket)

    return tickets        

def get_phriction_doc_by_phid(phid : str, api_base, api_token) -> dict | None:
    '''
    Returns a Phriction document based on the passed ID, or None if it's not found
    '''
    q = {
        'api.token': api_token,
        'constraints[documentPHIDs][]': phid, # This is hideous
        'attachments[content]': True, # So is this
        'limit': 1
    }
    res = requests.get(api_base + 'phriction.content.search', data=q)
    if res.status_code != 200:
        print(f'Error: {res.text}')
        return None
    return res.json()

def get_phriction_docs(limit, api_base, api_token, start = None, end = None) -> list[dict[str, str]]:
    '''
    Returns a list of the Phriction documents as a dict with the following keys:
    - title: Document title
    - PHID: Document PHID
    - Path: Document path
    - Content: Raw MD content
    '''
    def _ph_to_doc(ph_res : dict) -> dict[str, str | int]:
        '''
        Parses out the specific information from a Phab doc into the format needed for parsing
        '''
        return {
            'title': ph_res['attachments']['content']['title'],
            'path': ph_res['attachments']['content']['path'],
            'date_modified': ph_res['fields']['dateModified'],
            'PHID': ph_res['fields']['documentPHID'],
            'content': ph_res['attachments']['content']['content']['raw']
        }

    docs = []
    phab_data = []
    q = {
        'api.token': api_token,
        'order': 'newest',
        'attachments[content]': True
    }
    if limit == -1 or limit > 100:
        if limit != -1:
            num_calls = math.ceil(limit / 100) # The Phab API only allows 100 at most
            rem = limit % 100
            for _ in range(num_calls - 1):
                res = requests.get(api_base + 'phriction.content.search', data=q)
                if res.status_code != 200:
                    print(f'ERROR: {res.text}')
                    return []
                rjson = res.json()
                phab_data += rjson['result']['data']
                if rjson['result']['cursor']['after'] is None:
                    break
                q['after'] = rjson['result']['cursor']['after']
            q['limit'] = rem
            res = requests.get(api_base + 'phriction.content.search', data=q)
            if res.status_code != 200:
                print(f'ERROR: {res.text}')
                return []
            rjson = res.json()
            phab_data += rjson['result']['data']
        else: # Get all the docs
            while True:
                q['limit'] = 100
                res = requests.get(api_base + 'phriction.content.search', data=q)
                if res.status_code != 200:
                    print(f'ERROR: {res.text}')
                    return []
                rjson = res.json()
                phab_data += rjson['result']['data']
                if rjson['result']['cursor']['after'] is None:
                    break
                q['after'] = rjson['result']['cursor']['after']
    else:
        q['limit'] = limit
        res = requests.get(api_base + 'phriction.content.search', data=q)
        if res.status_code != 200:
            print(f'ERROR: {res.text}')
            return []
        phab_data = res.json()['result']['data']

    for d in phab_data:
        if start is not None and d['fields']['dateModified'] < start:
            continue
        if end is not None and d['fields']['dateModified'] > end:
            continue
        doc = _ph_to_doc(d)
        if len([e for e in docs if doc['PHID'] == e['PHID']]) == 0: # Since every version is treated as a different document/object
            docs.append(doc)

    return docs        

