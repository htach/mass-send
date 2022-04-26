
import json
import time
import asyncio
import httpx

from rich import print

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)

CONNECTIONS = int(input('Number of connections to use (1-100): '))

limits = httpx.Limits(max_connections=CONNECTIONS)
client = httpx.AsyncClient(
    cookies={'.ROBLOSECURITY': config.get('cookie')},
    limits=limits,
    timeout=None
)

queue, checked = asyncio.Queue(), set()

my_uaids, my_id = None, config.get('player_id')
receiving = list(map(int, config.get('receiving')))
giving = list(map(int, config.get('giving')))


def fprint(tag, color, content):
    current_time = time.strftime('%r')
    print(f'[[bold bright_black]{current_time}[/]] [bold {color}]{tag}[/] {content}')


async def fetch_owners(item_id, cursor=''):
    req = await client.get(f'https://inventory.roblox.com/v2/assets/{item_id}/owners?sortOrder=Desc&limit=100&cursor={cursor}')
    res = req.json()

    next_cursor, coros = res.get('nextPageCursor', None), []
    for i in res['data']:
        owner = i.get('owner', None)
        if not owner:
            continue

        owner_id = owner['id']
        if owner_id in checked or owner_id == my_id:
            continue

        coros.append(check(owner_id))
        checked.add(owner_id)

    await asyncio.gather(*coros)

    if next_cursor:
        await fetch_owners(item_id, next_cursor)


async def fetch_uaids(player_id, desired):
    req = await client.get(f'https://inventory.roblox.com/v1/users/{player_id}/assets/collectibles?limit=50')
    res = req.json()
    holder, uaids, data = [], [], res.get('data', None)
    if not data:
        return

    for i in data:
        item_id = i.get('assetId')
        if holder.count(item_id) < desired.count(item_id):
            uaids.append(i['userAssetId'])
            holder.append(item_id)

    return uaids


async def can_trade(player_id):
    req = await client.get(f'https://www.roblox.com/users/{player_id}/trade')
    return req.status_code == 200


async def check(player_id):
    uaids = await fetch_uaids(player_id, receiving)
    fprint('INFO', 'blue', f'Checking {player_id}')
    if await can_trade(player_id) and uaids:
        fprint('SUCESS', 'green', f'Queued trade with {player_id}')
        await queue.put({
            'offers': [
                {'userId': my_id, 'userAssetIds': my_uaids},
                {'userId': player_id, 'userAssetIds': uaids}
            ]}
        )


async def send_trades():
    while 1:
        if not queue.empty():
            trade = await queue.get()

            req = await client.post('https://auth.roblox.com/v1/xbox/disconnect')
            csrf_token = req.headers['x-csrf-token']

            req = await client.post(
                'https://trades.roblox.com/v1/trades/send',
                headers={'x-csrf-token': csrf_token},
                json=trade
            )
            res = req.json()

            if 'errors' not in res:
                fprint('SUCCESS', 'GREEN', f'Sent trade to {trade["offers"][1]["userId"]}')
            elif res['errors'][0]['code'] == 23:
                fprint('WARNING', 'YELLOW', f'Two step verification required https://www.roblox.com/my/account#!/security')
                await asyncio.sleep(30)

        await asyncio.sleep(10)


async def main():
    global my_uaids
    giving = list(map(int, config.get('giving')))
    my_uaids = await fetch_uaids(my_id, giving)

    await asyncio.gather(
        send_trades(),
        *(fetch_owners(i) for i in set(receiving))
    )

asyncio.get_event_loop().run_until_complete(main())
