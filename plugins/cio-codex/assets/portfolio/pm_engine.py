#!/usr/bin/env python3
# Policy-aware Portfolio Manager Decision Engine
# Computes bucket allocations and emits decision JSON + concise text.

import os, json, time
from decimal import Decimal, getcontext
getcontext().prec = 28

HOME = os.path.expanduser('~')
ROOT = os.path.join(HOME, '.hermes', 'portfolio')

D = lambda x: Decimal(str(x))


# Fund-name prefixes auto-classified as 'cashflow' (FI/SG). Empty by default;
# set to your fund families e.g. ('Acme Bond','Global Income') OR use bucket_overrides in rules.json.
CASHFLOW_FUND_PREFIXES = ()

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)


def classify_bucket(p, overrides):
    name = p.get('name', '')
    label = p.get('label', '')
    # explicit overrides
    for k, v in overrides.items():
        if k.startswith('name::') and name == k.split('::', 1)[1]:
            return v['bucket']
        if k.startswith('ticker::') and label == k.split('::', 1)[1]:
            return v['bucket']
    sec = p.get('sec')
    if name in ('PrivateFund', 'PrivateBiz'):
        return 'safety'
    if 'Gold' in name or label == 'IAU':
        return 'hedge'
    if sec in ('FI', 'SG') and name.startswith(CASHFLOW_FUND_PREFIXES):
        return 'cashflow'
    if name.startswith('Cash') or 'MMF' in name:
        return 'tactical'
    if sec in ('US', 'HK', 'JP'):
        return 'growth'
    return 'growth'


def compute_buckets(snapshot, rules):
    positions = snapshot['positions']
    mmf_to_safety = D(snapshot.get('mmf_to_safety_usd', 0))
    mmf_total = D(snapshot.get('mmf_total_usd', 0))

    val_by_bucket = {b: D('0') for b in ['safety', 'cashflow', 'growth', 'hedge', 'tactical']}

    # Safety: PrivateFund, PrivateBiz
    for p in positions:
        if p.get('name') in ('PrivateFund', 'PrivateBiz'):
            val_by_bucket['safety'] += D(p.get('value_usd', 0))

    # MMF split
    mmf_safety_alloc = min(mmf_to_safety, mmf_total)
    mmf_items = [(i, D(p.get('value_usd', 0))) for i, p in enumerate(positions) if p.get('name') in ('MMF USD', 'MMF2')]
    mmf_left = mmf_safety_alloc
    for idx, v in sorted(mmf_items, key=lambda x: 0 if positions[x[0]]['name'] == 'MMF USD' else 1):
        take = min(v, mmf_left)
        if take > 0:
            val_by_bucket['safety'] += take
            v_rem = v - take
            mmf_left -= take
            val_by_bucket['tactical'] += v_rem
        else:
            val_by_bucket['tactical'] += v

    # Cash USD -> tactical
    for p in positions:
        if p.get('name') == 'Cash USD':
            val_by_bucket['tactical'] += D(p.get('value_usd', 0))

    # Other positions
    overrides = rules.get('bucket_overrides', {})
    for p in positions:
        name = p.get('name')
        if name in ('PrivateFund', 'PrivateBiz', 'MMF USD', 'MMF2', 'Cash USD'):
            continue
        b = classify_bucket(p, overrides)
        val_by_bucket[b] += D(p.get('value_usd', 0))

    inv_total = D(snapshot.get('investable_total_usd')) if snapshot.get('investable_total_usd') is not None else (
        val_by_bucket['cashflow'] + val_by_bucket['growth'] + val_by_bucket['hedge'] + val_by_bucket['tactical']
    )
    port_total = sum(D(p.get('value_usd', 0)) for p in positions)

    return val_by_bucket, inv_total, port_total


def make_decision(snapshot, rules):
    val_by_bucket, inv_total, port_total = compute_buckets(snapshot, rules)
    gold_policy = rules.get('gold_policy', {'floor_hard': 0.03, 'floor_pref': 0.05, 'upper': 0.08})
    cash_policy = rules.get('cash_policy', {'min_investable': 0.05, 'pref_low': 0.08, 'pref_high': 0.12})

    gold_val = val_by_bucket['hedge']
    cash_val = val_by_bucket['tactical']
    gold_pct = (gold_val / inv_total * Decimal('100')) if inv_total > 0 else Decimal('0')
    cash_pct = (cash_val / inv_total * Decimal('100')) if inv_total > 0 else Decimal('0')

    stance = []
    primary_issue = ''
    rebalance_required = False

    if gold_pct < Decimal(str(gold_policy['floor_hard'])) * Decimal('100'):
        stance.append('under-hedged'); primary_issue = 'Gold hedge below hard floor'; rebalance_required = True
    elif gold_pct < Decimal(str(gold_policy['floor_pref'])) * Decimal('100'):
        stance.append('under-hedged'); primary_issue = 'Gold hedge below preferred floor'

    if cash_pct < Decimal(str(cash_policy['min_investable'])) * Decimal('100'):
        stance.append('cash-constrained'); primary_issue = primary_issue or 'Investable cash below minimum'; rebalance_required = True
    elif cash_pct < Decimal(str(cash_policy['pref_low'])) * Decimal('100'):
        stance.append('cashflow-light')

    growth_w = (val_by_bucket['growth'] / inv_total * Decimal('100')) if inv_total > 0 else Decimal('0')
    if growth_w > Decimal('50'): stance.append('growth-heavy')
    if not stance: stance = ['balanced']

    overall_status = 'action_needed' if rebalance_required else ('watch' if ('under-hedged' in stance or 'growth-heavy' in stance or 'cashflow-light' in stance) else 'healthy')

    # Bucket recs
    bucket_targets = {
        'hedge': (gold_policy['floor_pref'], gold_policy['upper']),
        'cashflow': (0.15, 0.35),
        'growth': (0.40, 0.65),
        'tactical': (cash_policy['pref_low'], cash_policy['pref_high'])
    }
    def status_for(b, pct):
        lo, hi = bucket_targets.get(b, (0.0, 1.0))
        if pct < Decimal(str(lo * 100)): return 'underweight'
        if pct > Decimal(str(hi * 100)): return 'overweight'
        return 'neutral'

    bucket_recs = []
    for b in ['hedge', 'cashflow', 'growth', 'tactical']:
        val = val_by_bucket[b]
        pct = (val / inv_total * Decimal('100')) if inv_total > 0 else Decimal('0')
        st = status_for(b, pct)
        rec = 'add' if st == 'underweight' else ('trim' if st == 'overweight' else 'hold')
        rationale = 'Within band'
        if st == 'underweight': rationale = 'Below target band'
        if st == 'overweight': rationale = 'Above target band'
        bucket_recs.append({
            'bucket_name': b,
            'current_weight': float(pct) / 100.0,
            'target_band': f"{int(bucket_targets[b][0] * 100)}-{int(bucket_targets[b][1] * 100)}%",
            'status': st,
            'recommended_action': rec,
            'rationale': rationale
        })

    # Security actions
    securities = []
    if gold_pct < Decimal(str(gold_policy['floor_pref'])) * Decimal('100'):
        iau = next((p for p in snapshot['positions'] if p.get('label') == 'IAU' or 'Gold' in p.get('name', '')), None)
        price = Decimal(str(iau['price'])) if iau and iau.get('price') is not None else None
        target_val = Decimal(str(gold_policy['floor_pref'])) * inv_total
        add_amt = (target_val - gold_val) if target_val > gold_val else Decimal('0')
        qty = int((add_amt / price).to_integral_value()) if price and price > 0 and add_amt > 0 else None
        securities.append({
            'ticker': 'IAU',
            'asset_type': 'gold_etf',
            'current_weight': float(gold_val / inv_total) if inv_total > 0 else 0.0,
            'target_weight_or_range': f">={int(gold_policy['floor_pref'] * 100)}%",
            'action': 'add' if add_amt > 0 else 'hold',
            'priority': 'high',
            'buy_band': 'staged accumulation zone',
            'suggested_amount': float(add_amt),
            'suggested_quantity': qty,
            'rationale': 'Under preferred gold floor per policy.',
            'key_risk': 'Gold drawdown; hedge timing risk.',
            'thesis_status': 'intact',
            'next_review_date': None
        })

    decision = {
        'timestamp': int(time.time()),
        'mode': 'portfolio_review',
        'policy_version': 'v1.1',
        'snapshot_id': None,
        'overall_status': overall_status,
        'portfolio_stance': stance,
        'primary_issue': primary_issue or None,
        'secondary_issue': None,
        'next_best_use_of_capital': 'Raise gold to preferred floor' if ('under-hedged' in stance) else ('Rebuild cash buffer' if 'cash-constrained' in stance else 'Close largest allocation gap'),
        'rebalance_required': overall_status == 'action_needed',
        'override_warning_if_any': None,
        'buckets': bucket_recs,
        'securities': securities[:5],
        'reasoning': 'Policy-driven assessment using latest valuation snapshot and rules.',
        'risks': 'Market volatility, data latency; actions constrained by policy.',
        'next_review_date': None
    }
    return decision


def main():
    rules = load_json(os.path.join(ROOT, 'portfolio_rules.json'))
    snap_dir = os.path.join(ROOT, 'snapshots')
    snaps = [os.path.join(snap_dir, f) for f in os.listdir(snap_dir) if f.endswith('.json') and 'valuation' in f]
    latest = max(snaps, key=os.path.getmtime)
    snapshot = load_json(latest)
    decision = make_decision(snapshot, rules)
    decision['snapshot_id'] = os.path.basename(latest)

    dec_dir = os.path.join(ROOT, 'decisions')
    os.makedirs(dec_dir, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    json_path = os.path.join(dec_dir, f'{stamp}_portfolio_review.json')
    with open(json_path, 'w') as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)

    # detailed text (CN) per user's fixed format preference
    def render_detailed(decision):
        bucket_cn = {
            'safety': '安全垫',
            'cashflow': '现金流',
            'growth': '成长',
            'hedge': '对冲',
            'tactical': '战术/流动性',
        }
        status_cn = {'underweight': '低配', 'overweight': '超配', 'neutral': '中性'}
        action_cn = {'add': '加仓', 'trim': '减仓', 'hold': '观望', 'exit': '清仓', 'watch': '观察'}
        status_map = {'action_needed': '需要动作', 'watch': '观察', 'healthy': '健康'}

        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(decision.get('timestamp', 0)))
        lines = []
        lines.append(f"决策时间: {ts}")
        lines.append(f"模式: {decision.get('mode','-')} · 政策版本: {decision.get('policy_version','-')}")
        if decision.get('snapshot_id'):
            lines.append(f"估值快照: {decision['snapshot_id']}")
        lines.append("")
        lines.append(f"总体状态: {status_map.get(decision.get('overall_status'), decision.get('overall_status','-'))}")
        stance = decision.get('portfolio_stance') or []
        if stance:
            lines.append(f"组合姿态: {', '.join(stance)}")
        if decision.get('primary_issue'):
            lines.append(f"主要问题: {decision['primary_issue']}")
        if decision.get('secondary_issue'):
            lines.append(f"次要问题: {decision['secondary_issue']}")
        lines.append(f"下一笔最优资本用途: {decision.get('next_best_use_of_capital','-')}")
        lines.append(f"是否触发再平衡: {'是' if decision.get('rebalance_required') else '否'}")
        lines.append("")
        lines.append("桶/类别诊断：")
        for b in decision.get('buckets', []):
            name = b.get('bucket_name','-')
            pct = b.get('current_weight')
            pct_str = f"{pct*100:.1f}%" if isinstance(pct, (int, float)) else '-'
            band = b.get('target_band','-')
            st = status_cn.get(b.get('status'), b.get('status','-'))
            rec = action_cn.get(b.get('recommended_action'), b.get('recommended_action','-'))
            rationale = b.get('rationale','-')
            lines.append(f"- {bucket_cn.get(name,name)}: 当前 {pct_str} | 目标 {band} | 状态 {st} | 建议 {rec} | 理由 {rationale}")
        lines.append("")
        lines.append("具体标的与操作：")
        secs = decision.get('securities', [])
        if not secs:
            lines.append("- （本期无具体标的操作建议）")
        else:
            for s in secs:
                t = s.get('ticker') or s.get('name','-')
                act = action_cn.get(s.get('action'), s.get('action','-'))
                amt = s.get('suggested_amount')
                qty = s.get('suggested_quantity')
                amt_str = (f"${amt:,.0f}" if isinstance(amt,(int,float)) else None) if amt else None
                qty_str = (f"~{qty} 单位" if isinstance(qty,int) else None) if qty else None
                tail_parts = [p for p in [amt_str, qty_str] if p]
                tail = ' · ' + ' · '.join(tail_parts) if tail_parts else ''
                lines.append(f"- {t}: {act}{tail}")
                cw = s.get('current_weight')
                cw_str = f"{cw*100:.2f}%" if isinstance(cw,(int,float)) else '-'
                tw = s.get('target_weight_or_range','-')
                band = s.get('buy_band') or s.get('trim_band') or '-'
                lines.append(f"  当前权重 {cw_str} | 目标 {tw} | 区域 {band}")
                rationale = s.get('rationale','-')
                risk = s.get('key_risk') or '-'
                thesis = s.get('thesis_status') or '-'
                nrd = s.get('next_review_date') or '-'
                lines.append(f"  理由: {rationale}")
                lines.append(f"  关键风险: {risk} | 论点: {thesis} | 下次回顾: {nrd}")
        lines.append("")
        if decision.get('reasoning'):
            lines.append(f"方法说明: {decision['reasoning']}")
        if decision.get('risks'):
            lines.append(f"通用风险: {decision['risks']}")
        return lines

    lines = render_detailed(decision)
    txt_path = os.path.join(dec_dir, f'{stamp}_portfolio_review.txt')
    with open(txt_path, 'w') as f:
        f.write('\n'.join(lines))

    print(json_path)
    print(txt_path)

if __name__ == '__main__':
    main()
