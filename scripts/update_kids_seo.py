"""Update all KiddoWorld video SEO with manually crafted metadata."""
import sys, time, re
sys.path.insert(0, "/root/uppercut")
from modules.uploader.youtube_uploader import _get_authenticated_service

yt = _get_authenticated_service(token_file="token_kiddoworld.json")
ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
uploads_pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]

all_vids = []
next_page = None
while True:
    pl = yt.playlistItems().list(part="contentDetails", playlistId=uploads_pl, maxResults=50, pageToken=next_page).execute()
    for item in pl["items"]:
        all_vids.append(item["contentDetails"]["videoId"])
    next_page = pl.get("nextPageToken")
    if not next_page:
        break

AI_NOTE = "\n\n\U0001f916 This video was created using AI animation tools."
SUB_NOTE = "\n\n\U0001f514 Subscribe to KiddoWorld for new kids songs every day!"

seo_map = {
    "Baby Shark Lullaby": {
        "title": "Baby Shark Lullaby \U0001f988\U0001f4a4 | Sleepy Time Songs for Babies | KiddoWorld",
        "tags": ["KiddoWorld", "baby shark lullaby", "nursery rhymes", "baby sleep music", "kids songs", "bedtime songs", "toddler lullaby", "short", "short feed"],
        "hook": "The sweetest Baby Shark lullaby to help your little ones fall asleep! \U0001f319",
        "hashtags": "#babyshark #lullaby #babysongs #sleepmusic #kiddoworld #nurseryrhymes #bedtime #toddlersongs #babysleep #kidsmusic",
    },
    "Friendly Dinosaur Adventure": {
        "title": "The Friendly Dinosaur Adventure \U0001f995\u2728 | Kids Stories | KiddoWorld #Shorts",
        "tags": ["KiddoWorld", "dinosaur story", "kids adventure", "nursery rhymes", "toddler stories", "short", "short feed"],
        "hook": "Join the friendliest dinosaur on an amazing adventure! \U0001f995",
        "hashtags": "#dinosaur #kidsstories #kiddoworld #nurseryrhymes #adventure #toddlers #preschool #shorts",
    },
    "Chicky Chacha": {
        "title": "Chicky Chacha Dance Song \U0001f423\U0001f483 | Dance Along for Kids | KiddoWorld",
        "tags": ["KiddoWorld", "kids dance song", "nursery rhymes", "toddler songs", "dance along", "happy song", "short", "short feed"],
        "hook": "Dance along with Chicky Chacha! \U0001f423 The happiest dance song for kids!",
        "hashtags": "#dancesong #kidsdance #kiddoworld #nurseryrhymes #toddlersongs #dancealong #happysong #kidsmusic",
    },
    "Wheels on the Bus for Kids!": {
        "title": "Wheels on the Bus Go Round and Round \U0001f68c\U0001f3b5 | KiddoWorld #Shorts",
        "tags": ["KiddoWorld", "wheels on the bus", "nursery rhymes", "kids songs", "baby songs", "classic", "short", "short feed"],
        "hook": "The wheels on the bus go round and round! \U0001f68c Sing along with this classic!",
        "hashtags": "#wheelsonthebus #nurseryrhymes #kidssongs #kiddoworld #babysongs #singalong #classic #shorts",
    },
    "123 Numbers Song for Kids - Count to 20 #Short": {
        "title": "123 Counting Song \U0001f522\U0001f3b5 | Learn Numbers 1-20 | KiddoWorld #Shorts",
        "tags": ["KiddoWorld", "counting song", "learn numbers", "nursery rhymes", "kids songs", "educational", "short", "short feed"],
        "hook": "Learn to count from 1 to 20 with this fun counting song! \U0001f522",
        "hashtags": "#counting #numbers #kidssongs #kiddoworld #nurseryrhymes #learntocount #educational #shorts",
    },
    "Friendly Dinosaur Story": {
        "title": "The Friendly Dinosaur Story \U0001f995\U0001f31f | Bedtime Stories | KiddoWorld #Shorts",
        "tags": ["KiddoWorld", "dinosaur story", "bedtime stories", "kids stories", "nursery rhymes", "short", "short feed"],
        "hook": "A gentle dinosaur story perfect for bedtime! \U0001f995",
        "hashtags": "#dinosaurstory #bedtimestories #kiddoworld #kidsstories #nurseryrhymes #toddlers #shorts",
    },
    "Johny Johny Morning Routine": {
        "title": "Johny Johny Yes Papa \U0001f3b5 | Morning Routine Song | KiddoWorld",
        "tags": ["KiddoWorld", "johny johny yes papa", "nursery rhymes", "morning routine", "kids songs", "classic", "toddler songs"],
        "hook": "Johny Johny Yes Papa! \U0001f3b5 The classic kids song with a fun morning routine!",
        "hashtags": "#johnyJohny #yesPapa #nurseryrhymes #kiddoworld #kidssongs #morningroutine #classic #babysongs",
    },
    "Wheels on the Bus Go Round | Kids Songs": {
        "title": "Wheels on the Bus \U0001f68c\u2728 | Nursery Rhymes & Kids Songs | KiddoWorld",
        "tags": ["KiddoWorld", "wheels on the bus", "nursery rhymes", "kids songs", "baby songs", "sing along", "toddler songs"],
        "hook": "Sing along with Wheels on the Bus! \U0001f68c The classic nursery rhyme for toddlers!",
        "hashtags": "#wheelsonthebus #nurseryrhymes #kidssongs #kiddoworld #babysongs #singalong #preschool #classic",
    },
    "Count and Dance All Day": {
        "title": "Count and Dance \U0001f483\U0001f522 | Fun Counting Song for Kids | KiddoWorld",
        "tags": ["KiddoWorld", "counting song", "dance song", "nursery rhymes", "kids songs", "educational", "toddler songs"],
        "hook": "Count and dance along! \U0001f483 A fun counting song that gets kids moving!",
        "hashtags": "#counting #dancesong #kiddoworld #nurseryrhymes #kidssongs #educational #toddlersongs #funforkids",
    },
    "Shiny Little Firefly": {
        "title": "Shiny Little Firefly \U0001f31f\u2728 | Magical Night Song | KiddoWorld",
        "tags": ["KiddoWorld", "firefly song", "bedtime song", "nursery rhymes", "magical", "kids songs", "lullaby", "short", "short feed"],
        "hook": "Watch the magical shiny firefly light up the night! \U0001f31f",
        "hashtags": "#firefly #nightsong #kiddoworld #bedtime #nurseryrhymes #kidssongs #magical #lullaby",
    },
    "Fun Nursery Rhymes for Kids": {
        "title": "Best Nursery Rhymes Collection \U0001f3b5\U0001f308 | Sing Along | KiddoWorld",
        "tags": ["KiddoWorld", "nursery rhymes", "kids songs", "baby songs", "sing along", "toddler songs", "collection"],
        "hook": "The best nursery rhymes collection for babies and toddlers! \U0001f3b5",
        "hashtags": "#nurseryrhymes #kidssongs #babysongs #kiddoworld #singalong #toddlersongs #collection #preschool",
    },
    "Bubble Bath Adventure": {
        "title": "Bubble Bath Time Song \U0001f6c1\U0001fae7 | Fun Bath Songs | KiddoWorld",
        "tags": ["KiddoWorld", "bath song", "bubble bath", "nursery rhymes", "kids songs", "bath time", "toddler songs"],
        "hook": "Splish splash it's bubble bath time! \U0001f6c1 A fun bath song for toddlers!",
        "hashtags": "#bubblebath #bathsong #kiddoworld #nurseryrhymes #kidssongs #bathtime #toddlersongs #funforkids",
    },
    "123 Numbers Song - Count to 20 for Kids": {
        "title": "Learn Numbers 1 to 20 \U0001f522\U0001f3b6 | Counting Song | KiddoWorld",
        "tags": ["KiddoWorld", "counting song", "learn numbers", "nursery rhymes", "educational", "toddler learning", "kids songs"],
        "hook": "Learn to count from 1 to 20! \U0001f522 Fun counting song for toddlers!",
        "hashtags": "#numbers #counting #kiddoworld #nurseryrhymes #educational #toddlerlearning #kidssongs #123",
    },
    "Animal Sounds Song for Kids! #Short": {
        "title": "Animal Sounds Song \U0001f436\U0001f431\U0001f42e | Learn Animal Sounds | KiddoWorld #Shorts",
        "tags": ["KiddoWorld", "animal sounds", "kids songs", "nursery rhymes", "learn animals", "educational", "short", "short feed"],
        "hook": "What sound does the cow make? Moo! \U0001f42e Learn all animal sounds!",
        "hashtags": "#animalsounds #kidssongs #kiddoworld #nurseryrhymes #animals #educational #shorts",
    },
    "Animal Sounds Song for Kids - Sing": {
        "title": "Animal Sounds for Kids \U0001f981\U0001f438\U0001f414 | Sing & Learn | KiddoWorld",
        "tags": ["KiddoWorld", "animal sounds", "sing and learn", "nursery rhymes", "kids songs", "educational", "toddler songs"],
        "hook": "Sing and learn all the animal sounds! \U0001f981 Fun for babies and toddlers!",
        "hashtags": "#animalsounds #kidssongs #kiddoworld #nurseryrhymes #learnanimals #educational #singalong",
    },
    "Happy Car Ride Adventure": {
        "title": "Happy Car Ride Song \U0001f697\U0001f3b5 | Fun Driving Song | KiddoWorld",
        "tags": ["KiddoWorld", "car song", "driving song", "nursery rhymes", "kids songs", "vehicles", "toddler songs", "short", "short feed"],
        "hook": "Beep beep! \U0001f697 Join the happy car ride adventure!",
        "hashtags": "#carsong #kiddoworld #nurseryrhymes #kidssongs #driving #toddlersongs #vehicles #funforkids",
    },
    "ABC Alphabet Song for Kids | Learn ABCs": {
        "title": "ABC Alphabet Song \U0001f524\U0001f3b6 | Learn Letters A to Z | KiddoWorld",
        "tags": ["KiddoWorld", "ABC song", "alphabet", "learn letters", "nursery rhymes", "kids songs", "educational"],
        "hook": "Sing the ABC song! \U0001f524 Learn all 26 letters from A to Z!",
        "hashtags": "#abcsong #alphabet #kiddoworld #nurseryrhymes #kidssongs #learnletters #educational #AtoZ",
    },
    "Shapes Song - Circle Square Triangle": {
        "title": "Shapes Song \u2b50\U0001f535\U0001f53a | Learn Shapes for Kids | KiddoWorld",
        "tags": ["KiddoWorld", "shapes song", "learn shapes", "nursery rhymes", "kids songs", "educational", "toddler learning"],
        "hook": "Circle, square, triangle! \u2b50 Learn all the shapes with this fun song!",
        "hashtags": "#shapes #shapessong #kiddoworld #nurseryrhymes #educational #learnshapes #toddlerlearning",
    },
    "Luna's Gentle Glow": {
        "title": "Luna's Gentle Glow \U0001f319\u2728 | Bedtime Stories for Kids | KiddoWorld",
        "tags": ["KiddoWorld", "bedtime story", "Luna", "sleep story", "nursery rhymes", "kids stories", "gentle", "lullaby"],
        "hook": "A beautiful bedtime story about Luna and her gentle glow \U0001f319",
        "hashtags": "#bedtimestory #luna #kiddoworld #sleepstory #nurseryrhymes #kidsstories #lullaby #nighttime",
    },
    "ABC Song | Learn Alphabet A to Z #Short": {
        "title": "ABC Song \U0001f524\U0001f3b5 | Quick Alphabet for Kids | KiddoWorld #Shorts",
        "tags": ["KiddoWorld", "ABC song", "alphabet", "nursery rhymes", "kids songs", "short", "short feed", "educational"],
        "hook": "The quickest way to learn your ABCs! \U0001f524",
        "hashtags": "#abcsong #alphabet #kiddoworld #nurseryrhymes #shorts #educational #learnletters",
    },
    "Happy Shark Family Song": {
        "title": "Baby Shark Family Song \U0001f988\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466 | Shark Dance | KiddoWorld",
        "tags": ["KiddoWorld", "baby shark", "shark family", "nursery rhymes", "kids songs", "dance song", "short", "short feed"],
        "hook": "Baby Shark doo doo doo! \U0001f988 The whole shark family is here!",
        "hashtags": "#babyshark #sharkfamily #kiddoworld #nurseryrhymes #kidssongs #dancesong #toddlersongs",
    },
    "Four Big Elephants Dancing": {
        "title": "Four Big Elephants Dancing \U0001f418\U0001f483 | Fun Animal Song | KiddoWorld",
        "tags": ["KiddoWorld", "elephant song", "animal song", "nursery rhymes", "kids songs", "dance song", "toddler songs"],
        "hook": "Four big elephants dancing and having fun! \U0001f418",
        "hashtags": "#elephants #animalsong #kiddoworld #nurseryrhymes #kidssongs #dancesong #animals #funforkids",
    },
    "Bunny's Number Adventure": {
        "title": "Bunny's Number Adventure \U0001f430\U0001f522 | Counting Fun | KiddoWorld",
        "tags": ["KiddoWorld", "counting", "bunny", "number adventure", "nursery rhymes", "kids songs", "educational", "short", "short feed"],
        "hook": "Join Bunny on a number adventure! \U0001f430 Learn to count!",
        "hashtags": "#bunny #counting #kiddoworld #nurseryrhymes #educational #numbers #toddlerlearning #adventure",
    },
    "Little Kangaroo's Fun Day": {
        "title": "Little Kangaroo's Fun Day \U0001f998\U0001f31e | Action Songs | KiddoWorld",
        "tags": ["KiddoWorld", "kangaroo song", "action song", "nursery rhymes", "kids songs", "jumping", "toddler songs"],
        "hook": "Jump along with Little Kangaroo on the most fun day ever! \U0001f998",
        "hashtags": "#kangaroo #actionsong #kiddoworld #nurseryrhymes #kidssongs #jumping #funforkids #animals",
    },
    "ABC Song | Learn Alphabet A to Z | Nursery": {
        "title": "ABC Alphabet Song \U0001f524\u2728 | Learn A to Z | Nursery Rhymes | KiddoWorld",
        "tags": ["KiddoWorld", "ABC song", "alphabet", "nursery rhymes", "learn letters", "kids songs", "educational", "short", "short feed"],
        "hook": "Learn the full alphabet from A to Z! \U0001f524 A classic ABC song!",
        "hashtags": "#abcsong #alphabet #nurseryrhymes #kiddoworld #kidssongs #educational #learnletters #AtoZ",
    },
    "ABC Alphabet Song for Kids \U0001f3b6 #Short": {
        "title": "ABC Song for Babies \U0001f524\U0001f3b5 | Alphabet Learning | KiddoWorld #Shorts",
        "tags": ["KiddoWorld", "ABC song", "baby songs", "alphabet", "nursery rhymes", "educational", "short", "short feed"],
        "hook": "The ABC song that babies love! \U0001f524",
        "hashtags": "#abcsong #alphabet #kiddoworld #babysongs #nurseryrhymes #shorts #educational #learnletters",
    },
}

updated = 0
failed = 0
skipped = 0

for vid_id in all_vids:
    resp = yt.videos().list(part="snippet", id=vid_id).execute()
    if not resp.get("items"):
        continue
    item = resp["items"][0]
    current_title = item["snippet"]["title"]
    cat = item["snippet"].get("categoryId", "22")

    matched = None
    for key, seo in seo_map.items():
        if key in current_title:
            matched = seo
            break

    if not matched:
        skipped += 1
        print("SKIP: %s" % current_title[:50])
        continue

    desc = matched["hook"] + SUB_NOTE + AI_NOTE + "\n\n" + matched["hashtags"]

    clean_tags = []
    for t in matched["tags"]:
        t = t.encode("ascii", errors="ignore").decode("ascii").strip()
        t = re.sub(r"[^a-zA-Z0-9 \-]", "", t).strip()
        if t and len(t) >= 2:
            clean_tags.append(t)

    try:
        yt.videos().update(
            part="snippet",
            body={
                "id": vid_id,
                "snippet": {
                    "title": matched["title"][:100],
                    "description": desc[:5000],
                    "tags": clean_tags,
                    "categoryId": cat,
                },
            },
        ).execute()
        updated += 1
        print("OK: %s" % matched["title"][:55])
        time.sleep(2)
    except Exception as e:
        failed += 1
        print("FAIL: %s - %s" % (current_title[:30], str(e)[:50]))

print("\nDone! Updated: %d, Failed: %d, Skipped: %d" % (updated, failed, skipped))
