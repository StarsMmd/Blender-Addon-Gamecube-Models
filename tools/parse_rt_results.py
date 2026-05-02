#!/usr/bin/env python3
"""Parse `tests/round_trip/run_round_trips.py` output into the markdown
tables we paste into `documentation/round_trip_test_progress.md`.

Reads either the live per-model lines (`absol... NBN=…  NIN=…  BBB=…  IBI=…  BNB=…`)
or the final summary table — last occurrence wins. Emits one table per
category (character/Pokémon vs map/scene), plus per-category averaged
breakdowns for BBB and IBI.

Usage:
    python3 tools/parse_rt_results.py /tmp/rt_pkx.txt > /tmp/rt_table.md
"""
import re
import sys

GAME_HINTS = {
    # XD-only Pokémon
    'nukenin', 'rayquaza', 'haganeil', 'frygon', 'achamo', 'miniryu',
    'bohmander', 'cerebi', 'gallop', 'usohachi', 'runpappa',
    'mage_0101', 'gba_emr_f_0101', 'rinto_0101', 'rinto_1101', 'rinto_1102',
    'gaderi_0101', 'mirrabo_0101', 'mcgroudon_1101', 'akami_m_a1', 'boss555_a1',
    'agehunt', 'darklugia', 'deoxys', 'kibanha',
    'D1_out', 'D2_rest_1', 'D6_out_all', 'M1_out', 'M2_out', 'M3_out', 'M3_shrine_1F',
    'fukuro', 'ken_a1',
}
COLO_HINTS = {
    'hinoarashi', 'hizuki_a1', 'ghos', 'showers', 'subame', 'lantern',
    'gangar', 'eievui', 'eifie', 'thunder', 'fire', 'freezer', 'entei', 'suikun',
    'houou', 'pikachu', 'kemusso', 'roselia', 'donmel', 'denryu', 'noctus',
    'metamon', 'fushigibana', 'lizardon', 'kyukon', 'booster', 'blacky',
    'absol', 'airmd', 'ametama', 'betbeton', 'cokodora', 'dirteng', 'ebiwalar',
    'gonyonyo', 'groudon', 'hakuryu', 'hassam', 'heracros', 'kairiky', 'kairyu',
    'kirlia', 'koduck', 'laplace', 'nendoll', 'nyoromo', 'patcheel',
    'ruffresia', 'sirnight', 'sunnygo', 'tropius', 'vibrava', 'kemusso',
}


def game_for(model):
    for hint in GAME_HINTS:
        if model == hint:
            return 'XD'
    for hint in COLO_HINTS:
        if model == hint:
            return 'Colo'
    return '?'


_LIVE_RE = re.compile(
    r'^\s+([A-Za-z0-9_\-\.]+)\.\.\.\s+'
    r'NBN=([\d.]+)%\(([\d./]+)\)\s+'
    r'NIN=([\d.]+)%\(([\d./]+)\)\s+'
    r'BBB=(?:([\d.]+)%\(([\d./]+)\)|ERR(?:OR:[^N]*?)?)\s+'
    r'IBI=(?:([\d.]+)%\(([\d./]+)\)|ERR(?:OR:[^B]*?)?)\s+'
    r'BNB=([\d.]+)%'
)
_TABLE_RE = re.compile(
    r'^([A-Za-z0-9_\-\.]+)\s+'
    r'([\d.]+)%\(([\d./]+)\)\s+'
    r'([\d.]+)%\(([\d./]+)\)\s+'
    r'(?:(?:([\d.]+)%\(([\d./]+)\))|(?:ERR))\s+'
    r'(?:(?:([\d.]+)%\(([\d./]+)\))|(?:ERR))\s+'
    r'([\d.]+)%'
)


def parse(path):
    seen = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip()
            m = _LIVE_RE.match(line) or _TABLE_RE.match(line)
            if not m:
                continue
            model = m.group(1)
            row = {
                'model': model,
                'game': game_for(model),
                'nbn': '%s%%(%s)' % (m.group(2), m.group(3)),
                'nin': '%s%%(%s)' % (m.group(4), m.group(5)),
                'bbb': '%s%%(%s)' % (m.group(6), m.group(7)) if m.group(6) else 'ERR',
                'ibi': '%s%%(%s)' % (m.group(8), m.group(9)) if m.group(8) else 'ERR',
                'bnb': '%s%%' % m.group(10),
                'nbn_pct': float(m.group(2)),
                'nin_pct': float(m.group(4)),
                'bbb_pct': float(m.group(6)) if m.group(6) else None,
                'ibi_pct': float(m.group(8)) if m.group(8) else None,
                'bnb_pct': float(m.group(10)),
            }
            seen[model] = row  # last occurrence wins (final summary > live)
    return list(seen.values())


def avg(values):
    vs = [v for v in values if v is not None]
    return sum(vs) / len(vs) if vs else 0.0


def health(p):
    if p < 21: return '🔴'
    if p < 41: return '🟠'
    if p < 61: return '🟡'
    if p < 81: return '🔵'
    return '✅'


def emit_table(rows, title):
    if not rows:
        return
    a_nbn = avg(r['nbn_pct'] for r in rows)
    a_nin = avg(r['nin_pct'] for r in rows)
    a_bbb = avg(r['bbb_pct'] for r in rows)
    a_ibi = avg(r['ibi_pct'] for r in rows)
    a_bnb = avg(r['bnb_pct'] for r in rows)

    print(f"### {title}")
    print()
    print(f"| Model | Game | NBN {health(a_nbn)} | NIN {health(a_nin)} | BBB {health(a_bbb)} | IBI {health(a_ibi)} | BNB {health(a_bnb)} |")
    print("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: r['model']):
        print(f"| {r['model']} | {r['game']} | {r['nbn']} | {r['nin']} | {r['bbb']} | {r['ibi']} | {r['bnb']} |")
    print()
    print(f"**Averages:** NBN {a_nbn:.1f}% · NIN {a_nin:.1f}% · BBB {a_bbb:.1f}% · IBI {a_ibi:.1f}% · BNB {a_bnb:.1f}%")
    print()


_BREAKDOWN_RE = re.compile(
    r'^\s+(BBB|IBI) breakdown: (.+)$'
)
_CAT_RE = re.compile(r'(\w+)=([\d.]+)%\(([\d.]+)/([\d.]+)\)')


def parse_categories(path):
    """Average per-category match/error/miss across every test, separately
    for BBB and IBI. Returns: {test_type: {category: (avg_match, avg_err, avg_miss, n)}}."""
    sums = {'BBB': {}, 'IBI': {}}
    counts = {'BBB': {}, 'IBI': {}}
    with open(path) as f:
        for line in f:
            m = _BREAKDOWN_RE.match(line.rstrip())
            if not m:
                continue
            test_type, body = m.group(1), m.group(2)
            for cm in _CAT_RE.finditer(body):
                cat, match, err, miss = cm.group(1), float(cm.group(2)), float(cm.group(3)), float(cm.group(4))
                if cat not in sums[test_type]:
                    sums[test_type][cat] = [0.0, 0.0, 0.0]
                    counts[test_type][cat] = 0
                sums[test_type][cat][0] += match
                sums[test_type][cat][1] += err
                sums[test_type][cat][2] += miss
                counts[test_type][cat] += 1
    out = {}
    for tt in sums:
        out[tt] = {
            cat: (sums[tt][cat][0] / counts[tt][cat],
                  sums[tt][cat][1] / counts[tt][cat],
                  sums[tt][cat][2] / counts[tt][cat],
                  counts[tt][cat])
            for cat in sums[tt]
        }
    return out


def emit_categories(cats, label):
    if not cats:
        return
    print(f"### {label} category breakdown")
    print()
    print("| Category | Match | Error | Miss | Models |")
    print("|---|---|---|---|---|")
    for cat in sorted(cats):
        m_, e_, mi_, n = cats[cat]
        print(f"| {cat} | {m_:.1f}% | {e_:.1f}% | {mi_:.1f}% | {n} |")
    print()


def main():
    rows = parse(sys.argv[1])
    map_re = re.compile(r'^[DM]\d+(_|$)')
    maps = [r for r in rows if map_re.match(r['model'])]
    chars = [r for r in rows if not map_re.match(r['model'])]

    print(f"Total: {len(rows)} models ({len(chars)} character/Pokémon, {len(maps)} map/scene)")
    print()
    emit_table(chars, "Character / Pokémon Models")
    emit_table(maps, "Map / Scene Models")

    cats = parse_categories(sys.argv[1])
    emit_categories(cats.get('BBB', {}), "BBB")
    emit_categories(cats.get('IBI', {}), "IBI")


if __name__ == '__main__':
    main()
