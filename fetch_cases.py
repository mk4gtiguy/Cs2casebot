import requests
import json
import random

# Fetch CS2 case data
url = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/crates.json"
print("📡 Fetching CS2 case data...")
response = requests.get(url)
data = response.json()
print(f"✅ Fetched {len(data)} cases!")

# Rarity mapping
RARITY_MAP = {
    "Mil-Spec Grade": "Blue",
    "Restricted": "Purple",
    "Classified": "Pink",
    "Covert": "Red",
    "Rare Special": "Gold"
}

# ONLY THESE CASES - The ones Keyless has (30-40 most popular)
# You can add/remove from this list
SELECTED_CASES = [
    # 2024-2025 cases (NEWEST)
    "Kilowatt Case",
    "Gallery Case",
    "Fever Case",
    
    # 2023
    "Revolution Case",
    
    # 2022
    "Recoil Case",
    "Dreams & Nightmares Case",
    
    # 2021
    "Operation Riptide Case",
    "Snakebite Case",
    
    # 2020
    "Operation Broken Fang Case",
    "Fracture Case",
    "Prisma 2 Case",
    
    # 2019
    "Shattered Web Case",
    "CS20 Case",
    "Prisma Case",
    
    # 2018
    "Danger Zone Case",
    "Horizon Case",
    "Clutch Case",
    
    # 2017
    "Spectrum 2 Case",
    "Operation Hydra Case",
    "Spectrum Case",
    
    # 2016
    "Glove Case",
    "Gamma 2 Case",
    "Gamma Case",
    "Chroma 3 Case",
    "Operation Wildfire Case",
    
    # 2015
    "Revolver Case",
    "Shadow Case",
    "Falchion Case",
    "Chroma 2 Case",
    "Chroma Case",
    
    # 2014
    "Operation Vanguard Weapon Case",
    "Operation Breakout Weapon Case",
    "Huntsman Weapon Case",
    "Operation Phoenix Weapon Case",
    
    # Plus some extra popular ones (your "5-10 more")
    "CS:GO Weapon Case",
    "eSports 2013 Case",
    "eSports 2014 Summer Case",
]

# Case prices (real CS2 market prices)
CASE_PRICES = {
    "Kilowatt Case": 3.50,
    "Gallery Case": 3.00,
    "Fever Case": 4.00,
    "Revolution Case": 2.50,
    "Recoil Case": 2.00,
    "Dreams & Nightmares Case": 2.50,
    "Operation Riptide Case": 3.00,
    "Snakebite Case": 2.50,
    "Operation Broken Fang Case": 3.50,
    "Fracture Case": 2.00,
    "Prisma 2 Case": 2.00,
    "Shattered Web Case": 4.00,
    "CS20 Case": 2.50,
    "Prisma Case": 2.50,
    "Danger Zone Case": 2.50,
    "Horizon Case": 2.50,
    "Clutch Case": 3.00,
    "Spectrum 2 Case": 3.00,
    "Operation Hydra Case": 4.00,
    "Spectrum Case": 2.50,
    "Glove Case": 4.00,
    "Gamma 2 Case": 2.50,
    "Gamma Case": 2.50,
    "Chroma 3 Case": 2.00,
    "Operation Wildfire Case": 3.00,
    "Revolver Case": 2.00,
    "Shadow Case": 2.00,
    "Falchion Case": 2.00,
    "Chroma 2 Case": 2.00,
    "Chroma Case": 2.00,
    "Operation Vanguard Weapon Case": 2.50,
    "Operation Breakout Weapon Case": 2.50,
    "Huntsman Weapon Case": 2.50,
    "Operation Phoenix Weapon Case": 2.50,
    "CS:GO Weapon Case": 2.00,
    "eSports 2013 Case": 2.00,
    "eSports 2014 Summer Case": 2.00,
}

# Emojis for cases
EMOJIS = [
    "📦", "🎯", "⚡", "🔥", "💎", "🌟", "🎨", "🌈",
    "💥", "🌅", "⚠️", "🤲", "🎪", "🏹", "🗡️", "🛡️",
    "👑", "🎰", "🎲", "🎳", "🎭", "🎪", "🎯", "🎱",
    "🔫", "🌙", "🎂", "💎", "⚡", "🌊", "🌪️", "🎇"
]

CONDITIONS = ["Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred"]

print("\n🔍 Filtering to selected cases...")

cases_dict = {}
emoji_index = 0

for case in data:
    case_name = case['name']
    
    # Skip if not in our selected list
    if case_name not in SELECTED_CASES:
        continue
    
    # Skip if no items
    if not case.get('contains'):
        continue
    
    # Create a clean ID
    clean_id = case_name.lower().replace(' ', '_').replace('&', 'and').replace("'", '').replace('(', '').replace(')', '')
    
    # Get emoji
    emoji = EMOJIS[emoji_index % len(EMOJIS)]
    emoji_index += 1
    
    # Get price
    price = CASE_PRICES.get(case_name, 2.00)
    
    items = []
    
    # Add regular items (limit to keep file manageable)
    for item in case['contains'][:8]:  # Max 8 regular items per case
        rarity_key = item['rarity']['name']
        rarity = RARITY_MAP.get(rarity_key, "Blue")
        condition = random.choice(CONDITIONS)
        
        items.append({
            "name": item['name'],
            "rarity": rarity,
            "condition": condition
        })
    
    # Add rare items (knives, etc.)
    if case.get('contains_rare'):
        for item in case['contains_rare'][:3]:  # Max 3 rare items
            tier = "Legendary"
            if "StatTrak" in item['name']:
                tier = "Mythic"
            elif "★" in item['name']:
                tier = "Legendary"
            
            items.append({
                "name": item['name'],
                "rarity": "Gold",
                "tier": tier,
                "condition": "Factory New"
            })
    
    # Create case entry
    cases_dict[clean_id] = {
        "name": case_name,
        "emoji": emoji,
        "price": price,
        "items": items
    }
    
    print(f"  ✅ {case_name} ({len(items)} items) - ${price:.2f}")

print(f"\n✅ Total: {len(cases_dict)} cases!")

# ============================================
# GENERATE THE OUTPUT
# ============================================

print("\n" + "="*60)
print("📋 COPY THIS INTO YOUR web_server.py AND main.py:")
print("="*60 + "\n")

print("CASES = {")

for key, case in cases_dict.items():
    print(f'    "{key}": {{')
    print(f'        "name": "{case["name"]}",')
    print(f'        "emoji": "{case["emoji"]}",')
    print(f'        "price": {case["price"]},')
    print(f'        "items": [')
    
    # Show all items
    for i, item in enumerate(case["items"]):
        tier_str = f', "tier": "{item.get("tier", "Common")}"' if item.get("tier") else ""
        comma = "," if i < len(case["items"]) - 1 else ""
        print(f'            {{"name": "{item["name"]}", "rarity": "{item["rarity"]}"{tier_str}, "condition": "{item.get("condition", "Field-Tested")}"}}{comma}')
    
    print(f'        ]')
    print(f'    }},')

print("}")

print("\n" + "="*60)
print("📊 STATISTICS:")
print("="*60)
print(f"  📦 Total Cases: {len(cases_dict)}")
total_items = sum(len(case["items"]) for case in cases_dict.values())
print(f"  🎯 Total Items: {total_items}")
print("="*60)