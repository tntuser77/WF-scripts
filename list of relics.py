import json
import re
import requests


LocalDump = 'lastData Dump.json'
relicInfo = "https://raw.githubusercontent.com/WFCD/warframe-items/refs/heads/master/data/json/Relics.json"



with open(LocalDump) as json_data:
    data = json.load(json_data)
    relicInfo = requests.get(relicInfo).json()

class Relics:
    def __init__(self, uniqueName, name, codexSecret, description, type, imageName, category, tradable, locations, rewards):
        self.uniqueName = uniqueName
        self.name = name
        self.codexSecret = codexSecret
        self.description = description
        self.type = type
        self.imageName = imageName
        self.category = category
        self.tradable = tradable
        self.locations = locations
        self.rewards = rewards

class localRelic:
    def __init__(self, Name, Count, allRewards):
        self.Name = Name
        self.Count = Count
        self.allRewards = allRewards
        self.goldReward = allRewards[-1] if allRewards else None

        # Safely extract 'urlName' without raising a KeyError if keys are missing
        market_data = getattr(self.goldReward, 'item', {}).get("warframeMarket") or {}
        self.goldUrlName = market_data.get("urlName", "")
        self.goldPrice = 


              

class localRelicReward:
    def __init__(self, rarity, chance, item):
        self.rarity = rarity
        self.chance = chance
        self.item = item


localRelics = []
allRelics = []

for relic in relicInfo:
    uniqueName = relic['uniqueName']
    name = relic['name']
    codexSecret = relic['codexSecret']
    description = relic['description']
    type = relic['type']
    imageName = relic['imageName']
    category = relic['category']
    tradable = relic['tradable']
    locations = relic['locations']
    rewards = []
    
    for reward in relic['rewards']:
        rarity = reward['rarity']
        chance = reward['chance']
        item = reward['item']

        rewards.append(localRelicReward(rarity, chance, item))
    
    allRelics.append(Relics(uniqueName, name, codexSecret, description, type, imageName, category, tradable, locations, rewards))



for item in data['MiscItems']:
    if 'Projection' in item["ItemType"]:
        uniqueName = item['ItemType']
        name = allRelics[[relic.uniqueName for relic in allRelics].index(uniqueName)].name
        count = item['ItemCount']
        rewards = allRelics[[relic.uniqueName for relic in allRelics].index(uniqueName)].rewards
        localRelics.append(localRelic(name, count, rewards))

# for relic in localRelics:
#     print(f"Relic Name: {relic.Name}, Count: {relic.Count}, Rare Reward: {[reward.item for reward in relic.allRewards if reward.rarity == 'Rare']}")


print(localRelics[1].goldUrlName)  # Print the goldUrlName attribute of the first relic

#{'name': 'Pyrana Prime Blueprint', 'uniqueName': '/Lotus/Types/Game/Projections/T1VoidProjectionLimboPrimeDBronze', 'warframeMarket': {'id': '5b2985e1eb069f04ea65b0ea', 'urlName': 'pyrana_prime_blueprint'}}