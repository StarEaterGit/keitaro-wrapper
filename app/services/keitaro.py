from typing import Any
import httpx

class KeitaroError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class KeitaroClient:
    """Only allowed requests: GET, campaign/stream POST, and *scoped* PUT.

    Deliberately no DELETE method and no offer updates.
    """
    def __init__(self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip('/')
        self.client = httpx.Client(
            base_url=self.base_url + '/admin_api/v1/',
            headers={'Api-Key': api_key, 'Accept': 'application/json'},
            timeout=20,
            follow_redirects=False,
            transport=transport,
        )

    def close(self):
        self.client.close()

    def _request(self, method: str, path: str, payload: dict | None = None, params: dict | None = None) -> Any:
        try:
            resp = self.client.request(method, path.lstrip('/'), json=payload, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data
        except httpx.HTTPStatusError as exc:
            # Don't return upstream response text (could include tokens/URLs).
            raise KeitaroError(502, f'Keitaro responded with HTTP {exc.response.status_code}') from exc
        except (httpx.RequestError, ValueError) as exc:
            raise KeitaroError(502, 'Keitaro connection or JSON response error') from exc

    def get(self, path: str, params: dict | None = None):
        return self._request('GET', path, params=params)

    def get_campaign(self, campaign_id: int):
        return self.get(f'campaigns/{campaign_id}')

    def get_streams(self, campaign_id: int):
        return self.get(f'campaigns/{campaign_id}/streams')

    def get_stream(self, stream_id: int):
        return self.get(f'streams/{stream_id}')

    def get_offer(self, offer_id: int):
        return self.get(f'offers/{offer_id}')

    def create_campaign(self, body: dict):
        return self._request('POST', 'campaigns', body)

    def create_stream(self, body: dict):
        return self._request('POST', 'streams', body)

    def activate_campaign(self, campaign_id: int):
        return self._request('PUT', f'campaigns/{campaign_id}', {'state': 'active'})

    def replace_stream_offers(self, stream_id: int, offers: list[dict]):
        # Per Keitaro Admin API, PUT updates only submitted fields.
        return self._request('PUT', f'streams/{stream_id}', {'offers': offers})
