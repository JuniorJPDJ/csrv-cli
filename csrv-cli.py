#!/usr/bin/env python3

import asyncio
import json
import sys
from collections import deque

import aiohttp
import bs4
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.patch_stdout import patch_stdout

# TODO: object with state holding and centralised reconnecting
# TODO: local commands system


class LoginFailedException(Exception):
	pass


class TooManyErrorsException(Exception):
	pass


class CraftserveException(Exception):
	pass


async def cmd_prompt(prompt_sess, ws):
	while True:
		with patch_stdout():
			result = await prompt_sess.prompt_async()
		if not result.startswith('.'):
			await send_command(ws, result)
		elif result in (".q", ".quit"):
			print("Bye.")
			pending = asyncio.all_tasks()
			for t in pending: t.cancel()
			# TODO: less workaroundy
		#elif result == ".stop":
			# https://craftserve.pl/s/{server_id}/switch
			# Body: STOP
		# elif result == ".start":
			# https://craftserve.pl/s/{server_id}/switch
			# Body: START
		# .expires: expiration date listing
		# .wallet: wallet balance get
		# .getaddr: getting all associated domain names
		# .setname: domain name setting
		# big amount of data on https://craftserve.pl/s/{server_id}/?json=1
		else:
			print("Unknown csrv-cli command!")


async def send_command(ws, command):
	await ws.send_json({"scope": "console", "op": "execute", "args": {"command": command}})


async def main(email, passw, server_id, debug):
	prompt_sess = PromptSession('> ', auto_suggest=AutoSuggestFromHistory())

	async with aiohttp.ClientSession() as session:
		login = await session.post("https://craftserve.pl/login", data={'email': email, 'password': passw}, allow_redirects=False)
		if login.status == 200:
			login_resp = bs4.BeautifulSoup(await login.text(), features="html.parser")
			login_failed_reason = login_resp.find('div', class_="alert")
			login_failed_reason = login_resp.find('span', class_="help-block") if login_failed_reason is None else login_failed_reason
			raise LoginFailedException(login_failed_reason.text.strip() if login_failed_reason is not None else None)
		assert login.status == 303
		assert login.headers['Location'] == 'https://craftserve.pl/account'

		print("Logged in")
		last_messages = deque(maxlen=101)
		off = False
		errors = 0
		errors_max = 3
		# csrv sends 100 last console messages on init

		while True:
			async with session.ws_connect(f'https://craftserve.pl/websocket/server?sid={server_id}', receive_timeout=10) as ws:
				await ws.send_json({"scope": "console", "op": "subscribe_console", "args": {"debug": False}})

				async def periodic():
					while not ws.closed:
						await send_command(ws, "3MBNGeogDpA0eIH5bCEdMvNjzt8xq6VnbnksEboZoEeXe")
						# some token given to me by Rekseto and Cubixmeister that prevents sleeping of the server
						await asyncio.sleep(2)
				ws_tasks = (loop.create_task(periodic()), loop.create_task(cmd_prompt(prompt_sess, ws)))

				try:
					async for msg in ws:
						if debug: print(msg)

						if msg.type == aiohttp.WSMsgType.TEXT:
							try:
								msg_json = json.loads(msg.data)

								if "error" in msg_json:
									if msg_json["error"] == "The server is off!":
										if not off:
											print("The server is off!")
										off = True

									else:
										errors += 1
										print("Error:", msg_json["error"])
										if errors > errors_max:
											raise TooManyErrorsException from CraftserveException(msg_json["error"])
									for t in ws_tasks: t.cancel()
									await ws.close()
									break

								if "stream" in msg_json:
									if off:
										off = False
										print("Server enabled!")
									errors = 0
									# reset state

									for line in msg_json['stream']:
										if line not in last_messages:
											print(line)
											last_messages.append(line)
							except:
								for t in ws_tasks: t.cancel()
								await ws.close()
								raise
						else:
							for t in ws_tasks: t.cancel()
							await ws.close()
							break
				except asyncio.TimeoutError as e:
					errors += 1
					for t in ws_tasks: t.cancel()
					print(f"Error: {e.__class__.__name__}{f' - {e}' if str(e) else ''}")
					if errors > errors_max:
						raise TooManyErrorsException from e
				if not off:
					print("Disconnected from console, reconnecting")
				await asyncio.sleep(2)


if __name__ == '__main__':
	DEBUG = False
	loop = asyncio.get_event_loop()
	loop.run_until_complete(main(sys.argv[1], sys.argv[2], sys.argv[3], debug=DEBUG))
