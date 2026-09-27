#!/usr/bin/env python3
"""Version a train-only research rebalance. Never relabel or alter val/test."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random


def rebalance(data, duplicate_pairs, seed=20260926):
    excluded = {}
    for pair in duplicate_pairs:
        for side in ('left', 'right'):
            if pair[side + '_split'] == 'train':
                excluded[pair[side]] = 'cross_split_phash_candidate_conservative_exclusion_not_confirmed_duplicate'
    positives, negatives = [], []
    for im in data['images']:
        if im['split'] != 'train' or im['id'] in excluded:
            continue
        if im['annotations']:
            positives.append(im)
        elif 'negative_' in im['id']:
            negatives.append(im)
        else:
            excluded[im['id']] = 'empty_label_nonnegative_filename_quarantine_not_all_confirmed_missing_labels'
    if not positives or not negatives:
        raise ValueError('Positive and negative train pools required')
    negatives.sort(key=lambda i: i['id'])
    random.Random(seed).shuffle(negatives)
    chosen = negatives[:len(positives)]
    ids = {i['id'] for i in positives + chosen}
    for im in negatives[len(chosen):]:
        excluded[im['id']] = 'negative_pool_not_selected_this_run_preserved_in_source'
    images = [i for i in data['images'] if i['split'] != 'train' or i['id'] in ids]
    return dict(data, version=2, images=images, rebalance={
        'seed':seed, 'selection':'All remaining positive train images plus an equal-sized deterministic negative sample.',
        'train_positive_images':len(positives), 'train_negative_images':len(chosen),
        'excluded_train':excluded, 'exclusion_counts':dict(Counter(excluded.values())),
        'val_test_unchanged':True, 'labels_modified':False,
        'limitations':['Filename is a quarantine heuristic, not proof of annotation completeness.',
                        'Remaining publisher labels can still be incomplete or semantically inconsistent.',
                        'Old test has already been inspected; this is a reused regression comparison, not a new blind holdout.']} )


def main():
    p=argparse.ArgumentParser();p.add_argument('dataset',type=Path)
    p.add_argument('--duplicate-audit',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=20260926)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Use a new output path')
    result=rebalance(json.loads(a.dataset.read_text()),json.loads(a.duplicate_audit.read_text())['pairs'],a.seed)
    result['parent_dataset_sha256']=hashlib.sha256(a.dataset.read_bytes()).hexdigest()
    result['duplicate_audit_sha256']=hashlib.sha256(a.duplicate_audit.read_bytes()).hexdigest()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print({k:v for k,v in result['rebalance'].items() if k!='excluded_train'})


if __name__=='__main__':main()
