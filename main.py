import os
import tempfile
import requests
from dotenv import load_dotenv
import telebot
import openai
import traceback
import logging

# Setup logging to both console and file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("error.log", encoding="utf-8")
    ]
)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

if not BOT_TOKEN or not OPENAI_API_KEY:
    logging.error("BOT_TOKEN or OPENAI_API_KEY not set. Please check your .env or Railway variables.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)
openai.api_key = OPENAI_API_KEY

# Choose any of: 'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'
VOICE_NAME = 'nova'  # You can change this

def log_user_interaction(user, action, extra=""):
    logging.info(f"User: {user} - {action} {extra}")

def transcribe_audio(file_path):
    """Transcribe audio using OpenAI Whisper API"""
    with open(file_path, "rb") as audio_file:
        transcript = openai.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript.text.strip()

def generate_gpt_reply(prompt, user_id):
    """Generate a reply using GPT-4"""
    system_prompt = (
        "You are Svarupa, an Indian spiritual guide. Use compassionate, poetic, yet grounded responses. "
        "No jargon. Respond as if inspired by Osho and Sadhguru. Always reflect empathy, and adapt your tone to the user's emotional state if it is apparent."
    )
    chat = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        user=str(user_id),
        max_tokens=200,
        temperature=0.8
    )
    return chat.choices[0].message.content.strip()

def synthesize_voice(text):
    """Synthesize voice using OpenAI TTS (Voice Engine) API"""
    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "tts-1",
        "input": text,
        "voice": VOICE_NAME
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.content  # This is the audio (mp3) binary
    else:
        logging.error(f"TTS API error: {response.text}")
        return None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    log_user_interaction(message.from_user.username, "started bot")
    bot.send_message(
        message.chat.id,
        "🗣️ *Welcome to Svarupa!*\n\n"
        "Send me a *voice message* and I will reply in a natural AI voice, powered by ChatGPT Voice.\n"
        "You can also send text if you prefer.\n\n"
        "Commands:\n"
        "/start or /help — Show this help message.",
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    user = message.from_user.username or message.from_user.id
    log_user_interaction(user, "sent voice message")
    ogg_path = wav_path = mp3_path = None
    try:
        # Download the voice file from Telegram
        file_info = bot.get_file(message.voice.file_id)
        ogg_bytes = bot.download_file(file_info.file_path)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            ogg_path = f.name
            f.write(ogg_bytes)

        # Convert OGG (opus) to WAV (PCM) for Whisper API
        wav_path = ogg_path.replace(".ogg", ".wav")
        conv_result = os.system(f"ffmpeg -y -i {ogg_path} -ar 16000 -ac 1 -c:a pcm_s16le {wav_path}")
        if conv_result != 0 or not os.path.exists(wav_path):
            raise RuntimeError("ffmpeg conversion failed.")

        # Transcribe speech to text
        transcript = transcribe_audio(wav_path)
        bot.send_message(message.chat.id, f"📝 You said: {transcript}")

        # Generate spiritual reply with GPT-4
        reply_text = generate_gpt_reply(transcript, message.from_user.id)
        bot.send_message(message.chat.id, "🔊 Let me reply in voice...")

        # Synthesize voice reply
        audio_data = synthesize_voice(reply_text)
        if audio_data:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                mp3_path = f.name
                f.write(audio_data)
            with open(mp3_path, "rb") as audio_file:
                bot.send_voice(message.chat.id, audio_file)
        else:
            bot.send_message(message.chat.id, reply_text)
    except Exception as e:
        err_msg = f"Voice handling error: {e}\n{traceback.format_exc()}"
        logging.error(err_msg)
        bot.send_message(message.chat.id, "Sorry, I couldn't process your voice message.")
    finally:
        # Clean up temp files if they exist
        for path in [ogg_path, wav_path, mp3_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    logging.warning(f"Failed to remove temp file {path}: {e}")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    user = message.from_user.username or message.from_user.id
    log_user_interaction(user, "sent text message")
    mp3_path = None
    try:
        reply_text = generate_gpt_reply(message.text, message.from_user.id)
        audio_data = synthesize_voice(reply_text)
        if audio_data:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                mp3_path = f.name
                f.write(audio_data)
            with open(mp3_path, "rb") as audio_file:
                bot.send_voice(message.chat.id, audio_file)
        else:
            bot.send_message(message.chat.id, reply_text)
    except Exception as e:
        err_msg = f"Text handling error: {e}\n{traceback.format_exc()}"
        logging.error(err_msg)
        bot.send_message(message.chat.id, "Sorry, I couldn't process your message.")
    finally:
        if mp3_path and os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except Exception as e:
                logging.warning(f"Failed to remove temp file {mp3_path}: {e}")

if __name__ == "__main__":
    logging.info
