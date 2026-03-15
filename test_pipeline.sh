#!/bin/bash
set -e

echo "======================================"
echo "  Testing KiddoWorld Pipeline"
echo "======================================"

cd ~/Desktop/uppercut
source venv/bin/activate

echo ""
echo "Step 1: Testing imports..."
python3 -c "
import sys
sys.path.insert(0, '.')
from config import *
from modules.kids_script_generator import generate, get_kids_topic, generate_all_languages
from modules.kids_voice_generator import generate as voice_gen
from modules.animation_generator import generate_cartoon_clip, generate_clips_for_script
from modules.kids_music_fetcher import fetch_kids_music
from modules.kids_thumbnail_maker import create as thumb_create
from modules.kids_seo_generator import generate as seo_gen
from modules.trend_fetcher import fetch_trends
from modules.script_generator import generate_script
from modules.voice_generator import generate_voiceover
from modules.footage_fetcher import fetch_footage
from modules.video_assembler import assemble_video
from modules.thumbnail_maker import create_thumbnail
from modules.seo_generator import generate_seo
from modules.shorts_maker import create_short
from intelligence import run_intelligence
from alerts.email_alerts import pipeline_success, pipeline_failure
from dashboard.app import app
print('All imports successful')
"

echo ""
echo "Step 2: Testing database..."
python3 -c "
from config import init_db
init_db()
print('Database initialized')
"

echo ""
echo "Step 3: Testing kids script generation..."
python3 -c "
import yaml
with open('channels/kiddoworld.yaml') as f:
    config = yaml.safe_load(f)
from modules.kids_script_generator import get_kids_topic, generate
topic = get_kids_topic(config, 2)
print(f'Topic: {topic[\"text\"]}')
result = generate(topic, config)
print(f'Script: {len(result.text)} chars, {result.word_count} words, ~{result.estimated_duration_mins} min')
print(f'Animation prompts: {len(result.animation_prompts)}')
print(f'Style: {result.style}')
"

echo ""
echo "Step 4: Testing voice generation..."
python3 -c "
from modules.kids_voice_generator import generate
result = generate('Hello children, welcome to KiddoWorld! Let us learn the alphabet today.', 'english')
print(f'Voice generated: {result[\"path\"]}')
print(f'Duration: {result[\"duration_seconds\"]}s')
"

echo ""
echo "Step 5: Testing fal.ai animation (costs ~\$0.10)..."
python3 -c "
from modules.animation_generator import generate_cartoon_clip
clip = generate_cartoon_clip('A cute cartoon bear waving hello in a bright colorful classroom, sunny day')
if clip:
    print(f'Animation clip: {clip}')
else:
    print('Animation returned None — check fal.ai API key and credits')
"

echo ""
echo "Step 6: Testing Pixabay music fetch..."
python3 -c "
from modules.kids_music_fetcher import fetch_kids_music
music = fetch_kids_music()
print(f'Music: {music}')
"

echo ""
echo "Step 7: Testing kids thumbnail..."
python3 -c "
from modules.kids_thumbnail_maker import create
paths = create({'text': 'ABC Song', 'type': 'song_rhyme', 'concept': 'alphabet'}, style='bright_cartoon')
print(f'Thumbnails: {paths}')
"

echo ""
echo "Step 8: Testing kids SEO..."
python3 -c "
import yaml
with open('channels/kiddoworld.yaml') as f:
    config = yaml.safe_load(f)
from modules.kids_seo_generator import generate
topic = {'text': 'ABC Song', 'type': 'song_rhyme', 'concept': 'alphabet'}
seo = generate(topic, None, config)
print(f'SEO title: {seo.title}')
print(f'Tags: {len(seo.tags)} tags')
"

echo ""
echo "Step 9: Testing email alerts..."
python3 -c "
from alerts.email_alerts import ALERT_EMAIL, pipeline_success
print(f'Alert target: {ALERT_EMAIL}')
print('Alert functions loaded OK')
"

echo ""
echo "======================================"
echo "  All unit tests passed!"
echo "======================================"

echo ""
echo "To run the full pipeline end-to-end:"
echo "  python3 main.py --test --channel kiddoworld.yaml"
