import requests
import re
import json
import shutil
import os 

from io import BytesIO
from zipfile import ZipFile
from urllib.request import urlopen
from datetime import date
from collections import defaultdict

headers = {
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
}

def getLatestReleaseURL(url, fileName):
    releaseURL = requests.get(url, headers=headers)
    for asset in releaseURL.json()["assets"]:
        if fileName in asset["browser_download_url"]:
            releaseURL = asset["browser_download_url"]
            print(releaseURL)
            return releaseURL

def downloadAndExtract(url, pathTo="./temp"):
    response = urlopen(url)
    zipfile = ZipFile(BytesIO(response.read()))
    zipfile.extractall(path=pathTo)
    for fileName in zipfile.namelist():
        return fileName

def loadTermMetaBank(url):
    response = urlopen(url)
    with ZipFile(BytesIO(response.read())) as zipfile:
        for fileName in zipfile.namelist():
            if fileName.startswith("term_meta_bank_") and fileName.endswith(".json"):
                return json.loads(zipfile.read(fileName))
    raise ValueError("No term_meta_bank_*.json found in zip")

def parseFreqMetaData(data):
    if not isinstance(data, dict):
        return None
    if "frequency" in data and "reading" in data:
        freq = data["frequency"]
        if not isinstance(freq, dict) or "value" not in freq:
            return None
        return {
            "value": freq["value"],
            "displayValue": freq.get("displayValue", str(freq["value"])),
            "reading": data["reading"],
        }
    if "value" in data:
        return {
            "value": data["value"],
            "displayValue": data.get("displayValue", str(data["value"])),
            "reading": None,
        }
    return None

def mergeFreqForSurfaces(freqLookup, surfaces, allowed_readings=None):
    seen = set()
    merged = []
    for surface in surfaces:
        if not surface:
            continue
        for item in freqLookup.get(surface, []):
            reading = item.get("reading")
            if reading is not None:
                if allowed_readings is None or reading not in allowed_readings:
                    continue
            key = (item["value"], item.get("displayValue"))
            if key not in seen:
                seen.add(key)
                merged.append({
                    "value": item["value"],
                    "displayValue": item["displayValue"],
                })
    return merged

def fileExists(path):
    filename, extension = os.path.splitext(path)
    counter = 1

    while os.path.exists(path):
        path = filename + "(" + str(counter) + ")" + extension
        counter += 1

    return path

def createDictonary():
    # JLPT level data:
    jlptReleaseURL = getLatestReleaseURL(
        "https://api.github.com/repos/Bluskyo/JLPT_Vocabulary/releases/latest", 
        "JLPT_vocab_ALL.json"
    )
    print("Fetching latest release of JLPT_Vocabulary...")
    jlptResponse = requests.get(jlptReleaseURL)
    if jlptResponse.status_code == 200:
        jlptData = jlptResponse.json()
    else:
        print("Could not find jlpt data!")
        jlptData = None
    
    # Pitch accent data:
    print("Reading wadoku pitch accents...")
    pitchData = {}
    with open("data/wadoku_pitchdb.json", "r", encoding="utf-8-sig") as file:
        pitchData = json.load(file)

    freqURL = "https://github.com/Kuuuube/yomitan-dictionaries/raw/main/dictionaries/JPDB_v2.2_Frequency_Kana_2024-10-13.zip"
    print("Fetching JPDB frequency data...")
    freqLookup = defaultdict(list)
    for expression, mode, data in loadTermMetaBank(freqURL):
        if mode != "freq":
            continue
        parsed = parseFreqMetaData(data)
        if parsed:
            freqLookup[expression].append(parsed)

    # Furigana Data:
    furiganaReleaseURL = getLatestReleaseURL(
        "https://api.github.com/repos/Doublevil/JmdictFurigana/releases/latest", 
        "JmdictFurigana.json.zip"
    )
    print("Fetching latest release of JmdictFurigana...")
    furiganaFileName = downloadAndExtract(furiganaReleaseURL, "./temp")

    with open(f"temp/{furiganaFileName}", "r", encoding="utf-8-sig") as file:
        data = json.load(file)
        furiganaLookup = defaultdict(list)

        for entry in data:
            furiganaLookup[entry["text"]].append({
                "reading": entry["reading"],
                "furigana": entry["furigana"]
            })

    # JMDict data: 
    jmdictReleaseURL = requests.get(
        "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest", 
        headers=headers
    )
    print("Fetching latest release of jmdict-simplified...")
    fileRegex = r"jmdict-eng-(?!.*common).*\.json\.zip$"

    for asset in jmdictReleaseURL.json()["assets"]:
        link = asset["browser_download_url"]
        if re.search(fileRegex, link):
            jmdictReleaseURL = link
            break

    jmdictFileName = downloadAndExtract(jmdictReleaseURL, "./temp")
    jmdictData = {}

    print("Creating JMDict_Extended file...")
    with open(f"temp/{jmdictFileName}", "r", encoding="utf-8-sig") as file:
        jmdictData = json.load(file)

        print("Adding data to JMDict!")
        for entry in jmdictData["words"]:

            readings = {k.get("text") for k in entry["kana"]}

            # for every word with kanji add furigana, pitch accent and jlpt level data.
            for kanjiObject in entry["kanji"]:
                kanji = kanjiObject.get("text")

                kanjiObject["furigana"] = []
                kanjiObject["jlptLevel"]  = None
                kanjiObject["pitchAccent"] = []
                if kanji:
                    kanjiObject["freq"] = mergeFreqForSurfaces(
                        freqLookup, [kanji], readings
                    )
                    if not kanjiObject["freq"]:
                        kanjiObject["freq"] = mergeFreqForSurfaces(
                            freqLookup, readings, readings
                        )
                else:
                    kanjiObject["freq"] = []

                variants = furiganaLookup.get(kanji, [])

                for variant in variants:
                    if variant["reading"] in readings:
                        kanjiObject["furigana"] = variant["furigana"]
                        break

                jlptObject = jlptData.get(kanji)
                if jlptObject:
                    for jlptEntry in jlptObject:
                        if jlptEntry.get("reading") in readings: # check that the kanji and readings match
                            kanjiObject["jlptLevel"] = jlptEntry.get("level")
                            break

                pitchObject = pitchData.get(kanji)

                if (pitchObject):
                    if pitchData[kanji]["hira"][0] in readings:
                        kanjiObject["pitchAccent"] = {
                            "hatsuon" : pitchData[kanji]["hatsuon"][0],
                            "accPatts" : pitchData[kanji]["acc_patts"][0],
                            "zoPatts" : pitchData[kanji]["zo_patts"][0]
                        }

            # for every reading/hiragana word add furigana, pitch accent and jlpt level data.
            for kanaObject in entry["kana"]:
                kana = kanaObject.get("text")
                kanaObject["jlptLevel"]  = None
                kanaObject["pitchAccent"] = []
                kanaObject["freq"] = mergeFreqForSurfaces(
                    freqLookup,
                    [kana] if kana else [],
                    {kana} if kana else None,
                )

                jlptObject = jlptData.get(kana)
                if jlptObject:
                    for jlptEntry in jlptObject:
                        if jlptEntry.get("reading") in readings:
                            kanaObject["jlptLevel"] = jlptEntry.get("level")

                if (pitchData.get(kana)):
                    kanaObject["pitchAccent"] = {
                        "hatsuon" : pitchData[kana]["hatsuon"][0],
                        "accPatts" : pitchData[kana]["acc_patts"][0],
                        "zoPatts" : pitchData[kana]["zo_patts"][0]
                    }

    today = date.today().strftime("%Y-%m-%d")
    currentDirectory = os.getcwd()
    path = f"{currentDirectory}/result/jmdictExtended-{today}.json"
    path = fileExists(path)

    # write to file:
    beforeEntries = "{" + f"""
    "version": {json.dumps(jmdictData.get("version"), ensure_ascii=False)},
    "languages": {json.dumps(jmdictData.get("languages"), ensure_ascii=False)},
    "commonOnly": {json.dumps(jmdictData.get("commonOnly"), ensure_ascii=False)},
    "dictDate": {json.dumps(jmdictData.get("dictDate"), ensure_ascii=False)},
    "dictRevisions": {json.dumps(jmdictData.get("dictRevisions"), ensure_ascii=False)},
    "tags": {json.dumps(jmdictData.get("tags"), ensure_ascii=False)},
    "words": [""" 
    with open(f"{path}", "w", encoding="utf-8-sig") as f:
        f.write(beforeEntries)
        words = jmdictData["words"]
        for i, entry in enumerate(words):
            suffix = ",\n" if i < len(words) - 1 else "\n"
            f.write(f"{json.dumps(entry, ensure_ascii=False, separators=(',', ':'))}{suffix}")
        f.write("]" + "}")

    # remove temporary directory after file is made.
    print("deleting temporary files...")
    tempDelete = shutil.rmtree("temp/")
    print("Deleted temporary files!")
    print("DONE...")

if __name__ == "__main__":
    createDictonary()