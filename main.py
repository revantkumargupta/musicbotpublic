import os
import re 
import keys 
import utils
import shutil
import requests 
from bson import ObjectId
from aioify import aioify
import deezloader.deezloader
from urllib.parse import quote
from pymongo import MongoClient
from pydrive.auth import GoogleAuth
from pyrogram import Client, filters 
from pydrive.drive import GoogleDrive
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


bot = Client(
    "bot",
    api_id=keys.api_id,
    api_hash=keys.api_hash,
    bot_token=keys.bot_token
)
links = MongoClient(keys.db_url)["deezer_bot"]["links"]

@bot.on_message(filters.command("start"))
async def start_message(client, message):
    await message.reply_text("Hello")


@bot.on_message(filters.regex(r"^https?:\/\/(?:www\.)?deezer\.com\/([a-z]*\/)?album\/(\d+)\/?$"))
@bot.on_message(filters.regex(r"https?:\/\/(?:www\.)?deezer\.com\/([a-z]*\/)?track\/(\d+)\/?$"))
@bot.on_message(filters.regex(r"^https?:\/\/(?:www\.)?deezer\.com\/([a-z]*\/)?playlist\/(\d+)\/?$"))
async def deezer_input(client, message):
    item_id = message.matches[0].group(2)
    if re.match(r"^https?:\/\/(?:www\.)?deezer\.com\/([a-z]*\/)?playlist\/(\d+)\/?$", message.text):
        media_type = 'playlist'
        title = None
        
    elif re.search("https://www.deezer.com/track/", message.text):
        media_type = "track"
        data = requests.get(f"https://api.deezer.com/track/{item_id}").json()
        cover = data.get('album', {}).get('cover_medium')
        cover_link = data.get('album', {}).get('link')
        item_link = data.get('link')
        title = data.get('title')
        await message.reply_photo(cover, caption=data.get('title', ''), reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("Link", url=item_link),
                InlineKeyboardButton("Album Link", url=cover_link)
            ]]
        ))
    else:
        media_type = 'album'
        data = requests.get(f"https://api.deezer.com/album/{item_id}").json()
        cover = data.get('cover_medium')
        item_link = data.get('link')
        title = data.get('title')
        await message.reply_photo(cover, caption=data.get('title', ''), reply_markup=InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("Link", url=item_link),
            ]]
        ))
    link = links.insert_one({"link":message.text, 'expire_at': datetime.utcnow() + timedelta(hours=24), 'type': media_type, 'title':title, 'service':'deezer'})
    await message.reply_text("Select any one of the following options:", reply_markup=InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Google Drive", callback_data=f"gd_{link.inserted_id}"),
            InlineKeyboardButton("Telegram", callback_data=f"tg_{link.inserted_id}")
        ]]
    ))


@bot.on_message(filters.regex(r"^https://open.spotify.com/album"))
@bot.on_message(filters.regex(r"^https://open.spotify.com/track"))
@bot.on_message(filters.regex(r"^https://open.spotify.com/playlist"))
async def spotify_input(client, message):
    if re.search(r"^https://open.spotify.com/album", message.text):
        media_type = 'album'
    elif re.search(r"^https://open.spotify.com/playlist", message.text):
        media_type = 'playlist'
    else:
        media_type = 'track'

    link = links.insert_one({"link":message.text, 'expire_at': datetime.utcnow() + timedelta(hours=24), 'type': media_type, 'service':'spotify'})
    await message.reply_text("Select any one of the following options:\n", reply_markup=InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Google Drive", callback_data=f"gd_{link.inserted_id}"),
            InlineKeyboardButton("Telegram", callback_data=f"tg_{link.inserted_id}")
        ]]
    ))


@bot.on_callback_query(filters.regex("(gd|tg)_(.+)"))
async def handle_callback_query(client, callback_query):
    try:
        url = None 
        await callback_query.message.edit("Processing...")
        link = links.find_one({"_id": ObjectId(callback_query.matches[0].group(2))})
        if link is None:
            await callback_query.answer("Timeout!", show_alert=True)
            return
        link_type = link['type']
        service = link['service']
        title_dict = link
        link = link['link']
        action = callback_query.matches[0].group(1)
        await callback_query.message.edit("Downloading...")
        if service == 'deezer':
            if link_type == 'album':
                dl = await download.download_albumdee(
                    link, output_dir="tmp", 
                    quality_download='FLAC',     
                    recursive_download=True,
                    recursive_quality=True, 
                    not_interface=True
                )

            elif link_type == 'playlist':
                dl = await download.download_playlistdee(
                    link, output_dir="tmp",
                    quality_download='FLAC',
                    recursive_download=True,
                    recursive_quality=True,
                    not_interface=True
                )
            elif link_type == 'track':
                dl = await download.download_trackdee(
                    link, output_dir="tmp",
                    quality_download='FLAC',
                    recursive_download=True,
                    recursive_quality=True,
                    not_interface=True
                )
                if action == 'tg':
                    await callback_query.message.reply_audio(
                        dl.song_path,
                        duration=int(utils.get_flac_duration(dl.song_path))
                    )
                    return await callback_query.message.edit('Processed!')
                else:
                    file = drive.CreateFile({
                            'title': title_dict.get('title', dl.song_path.split('/')[-2]),
                            'parents': [{
                            'teamDriveId': keys.team_drive_id,
                            'id': keys.folder_id
                        }]
                    })
                    file.SetContentFile(dl.song_path)
                    file.Upload(param={'supportsTeamDrives': True})
                    url = f"https://drive.google.com/file/d/{file['id']}/view"
                    url2 = f"{keys.index_link}{quote(string=title_dict.get('title', dl.song_path.split('/')[-2]))}"
                    os.remove(dl.song_path)
                return await callback_query.message.edit("Processed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Google Drive", url=url), InlineKeyboardButton("Link", url=url2)]]) if url else None)

        else:
            if link_type == 'album':
                dl = await download.download_albumspo(
                    link, output_dir="tmp",
                    quality_download='FLAC',
                    recursive_download=True,
                    recursive_quality=True,
                    not_interface=True
                )
            elif link_type == 'playlist':
                dl = await download.download_playlistspo(
                    link, output_dir="tmp",
                    quality_download='FLAC',
                    recursive_download=True,
                    recursive_quality=True,
                    not_interface=True
                )
            elif link_type == 'track':
                dl = await download.download_trackspo(
                    link, output_dir="tmp",
                    quality_download='FLAC',
                    recursive_download=True,
                    recursive_quality=True,
                    not_interface=True
                )
                if action == 'tg':
                    await callback_query.message.reply_audio(
                        dl.song_path,
                        duration=int(utils.get_flac_duration(dl.song_path))
                    )
                    return await callback_query.message.edit('Processed!')
                else:
                    file = drive.CreateFile({
                            'title': dl.song_path.split('/')[-2],
                            'parents': [{
                            'teamDriveId': keys.team_drive_id,
                            'id': keys.folder_id
                        }]
                    })
                    file.SetContentFile(dl.song_path)
                    file.Upload(param={'supportsTeamDrives': True})
                    url = f"https://drive.google.com/file/d/{file['id']}/view"
                    url2 = f"{keys.index_link}{quote(string=dl.song_path.split('/')[-2])}"
                    os.remove(dl.song_path)
                return await callback_query.message.edit("Processed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Google Drive", url=url), InlineKeyboardButton("Link", url=url2)]]) if url else None)

        await callback_query.message.edit("Uploading...")
        if action == 'tg':
            for song in dl.tracks:
                await callback_query.message.reply_audio(
                    song.song_path,
                    duration=int(utils.get_flac_duration(song.song_path))
                )
        else:
            name = dl.tracks[0].song_path.split('/')[-2]
            shutil.make_archive(name, 'zip', 'tmp')
            file = drive.CreateFile({
                            'title': title_dict.get('title', 'file'),
                            'parents': [{
                            'teamDriveId': keys.team_drive_id,
                            'id': keys.folder_id
                        }]
                    })
            file.SetContentFile(f'{name}.zip')
            file.Upload(param={'supportsTeamDrives': True})
            url = f"https://drive.google.com/file/d/{file['id']}/view"
            url2 = f"{keys.index_link}{quote(string=title_dict.get('title', 'file'))}"
            os.remove(f'{name}.zip')
        for path in dl.tracks:
            try: shutil.rmtree(os.path.dirname(path.song_path))
            except: pass 
        await callback_query.message.edit("Processed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Google Drive", url=url), InlineKeyboardButton("Link", url=url2)]]) if url else None
        )
    except Exception as error:
        await callback_query.message.reply(f"Error : {error}")
        raise error 


if __name__ == "__main__":
    deezloader_async = aioify(obj=deezloader.deezloader, name='deezloader_async')
    download = deezloader_async.DeeLogin(keys.deezer_api)

    try: os.mkdir("tmp")
    except FileExistsError: pass

    links.create_index("expire_at", expireAfterSeconds=0)

    os.system(f'curl {keys.service_file_url} -O')
    gauth = GoogleAuth()
    scope = ["https://www.googleapis.com/auth/drive"]
    gauth.credentials = ServiceAccountCredentials.from_json_keyfile_name(keys.service_file, scope)
    drive = GoogleDrive(gauth)

    bot.run()
