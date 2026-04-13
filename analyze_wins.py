import json

with open('data/learning_database.json', 'r') as f:
    raw = json.load(f)

data = raw.get('operations', [])

wins = [t for t in data if t.get('result') == 'win']
losses = [t for t in data if t.get('result') == 'loose']

print(f"=== WIN/LOSS ANALYSIS ===")
print(f"Total wins: {len(wins)}")
print(f"Total losses: {len(losses)}")
print(f"Win rate: {len(wins)/(len(wins)+len(losses))*100:.1f}%")
print()

strategies = {}
actions = {}
trends = {}
conf_sum = 0
conf_count = 0

for t in wins:
    strat = t.get('strategy', {})
    strat_name = strat.get('strategy', 'Unknown')
    action = strat.get('action', 'Unknown')
    trend = t.get('movement', {}).get('trend', 'Unknown')
    conf = strat.get('confidence', 0)
    
    strategies[strat_name] = strategies.get(strat_name, 0) + 1
    actions[action] = actions.get(action, 0) + 1
    trends[trend] = trends.get(trend, 0) + 1
    conf_sum += conf
    conf_count += 1

print("=== WINNING STRATEGIES ===")
for s, c in sorted(strategies.items(), key=lambda x: -x[1]):
    print(f"  {s}: {c}")

print("\n=== WINNING ACTIONS ===")
for a, c in sorted(actions.items(), key=lambda x: -x[1]):
    print(f"  {a}: {c}")

print("\n=== WINNING TRENDS ===")
for tr, c in sorted(trends.items(), key=lambda x: -x[1]):
    print(f"  {tr}: {c}")

print(f"\n=== AVG CONFIDENCE (wins) ===")
print(f"  {conf_sum/conf_count:.1f}%")

# Compare with losses
print("\n=== LOSS STRATEGIES ===")
loss_strategies = {}
for t in losses:
    strat = t.get('strategy', {})
    strat_name = strat.get('strategy', 'Unknown')
    loss_strategies[strat_name] = loss_strategies.get(strat_name, 0) + 1
for s, c in sorted(loss_strategies.items(), key=lambda x: -x[1])[:10]:
    print(f"  {s}: {c}")

print("\n=== LOSS TRENDS ===")
loss_trends = {}
for t in losses:
    trend = t.get('movement', {}).get('trend', 'Unknown')
    loss_trends[trend] = loss_trends.get(trend, 0) + 1
for tr, c in sorted(loss_trends.items(), key=lambda x: -x[1]):
    print(f"  {tr}: {c}")

# Key differences
print("\n=== KEY INSIGHTS ===")
for strat in strategies:
    win_count = strategies.get(strat, 0)
    loss_count = loss_strategies.get(strat, 0)
    total = win_count + loss_count
    if total > 5:
        wr = win_count / total * 100
        print(f"  {strat}: {wr:.0f}% WR ({win_count}W/{loss_count}L)")
