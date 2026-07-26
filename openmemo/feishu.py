"""Feishu bot integration for OpenMemo"""
import json
import hashlib
import time
import httpx
from .config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_VERIFICATION_TOKEN


class FeishuBot:
    """Handles Feishu bot webhook and API calls"""
    
    def __init__(self):
        self.app_id = FEISHU_APP_ID
        self.app_secret = FEISHU_APP_SECRET
        self.verification_token = FEISHU_VERIFICATION_TOKEN
        self._tenant_access_token = None
        self._token_expires = 0
    
    def verify_event(self, body: dict) -> bool:
        """Verify incoming Feishu event
        
        Args:
            body: The request body from Feishu
        
        Returns:
            True if verification passes
        """
        # Handle URL verification challenge
        if body.get("type") == "url_verification":
            return True
        
        # Verify token
        token = body.get("token", "")
        if self.verification_token and token != self.verification_token:
            return False
        
        return True
    
    def handle_challenge(self, body: dict) -> dict:
        """Handle Feishu URL verification challenge
        
        Args:
            body: The challenge request body
        
        Returns:
            dict with challenge response
        """
        challenge = body.get("challenge", "")
        return {"challenge": challenge}
    
    async def get_tenant_access_token(self) -> str:
        """Get or refresh tenant access token"""
        if self._tenant_access_token and time.time() < self._token_expires:
            return self._tenant_access_token
        
        if not self.app_id or not self.app_secret:
            return None
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            data = response.json()
        
        if data.get("code") == 0:
            self._tenant_access_token = data["tenant_access_token"]
            self._token_expires = time.time() + data.get("expire", 7200) - 300
            return self._tenant_access_token
        else:
            print(f"Failed to get tenant token: {data}")
            return None
    
    async def send_message(self, receive_id: str, text: str, 
                           receive_id_type: str = "open_id") -> bool:
        """Send a text message to a Feishu user
        
        Args:
            receive_id: The user's open_id or chat_id
            text: Message text
            receive_id_type: Type of receive_id (open_id, chat_id, user_id)
        
        Returns:
            True if sent successfully
        """
        token = await self.get_tenant_access_token()
        if not token:
            print("No tenant access token available")
            return False
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        params = {"receive_id_type": receive_id_type}
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text})
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers, params=params)
                data = response.json()
            
            if data.get("code") == 0:
                return True
            else:
                print(f"Failed to send message: {data}")
                return False
        except Exception as e:
            print(f"Error sending message: {e}")
            return False
    
    def extract_message(self, body: dict) -> dict:
        """Extract message content from Feishu event body
        
        Args:
            body: The event body from Feishu webhook
        
        Returns:
            dict with 'text', 'open_id', 'message_id', 'msg_type'
        """
        event = body.get("event", {})
        message = event.get("message", {})
        
        msg_type = message.get("message_type", "text")
        content_str = message.get("content", "{}")
        
        try:
            content = json.loads(content_str)
        except json.JSONDecodeError:
            content = {}
        
        # Extract text
        text = ""
        if msg_type == "text":
            text = content.get("text", "")
        elif msg_type == "audio":
            # Voice message - Feishu provides STT result
            text = content.get("text", content.get("recognition", ""))
        
        sender = event.get("sender", {})
        open_id = sender.get("sender_id", {}).get("open_id", "default_user")
        message_id = message.get("message_id", "")
        
        return {
            "text": text,
            "open_id": open_id,
            "message_id": message_id,
            "msg_type": msg_type
        }


# Singleton instance
feishu_bot = FeishuBot()
