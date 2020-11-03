# pylint: disable=no-name-in-module
# pylint: disable=import-error
import argparse
import os
import numpy as np
from functools import partial
from operator import itemgetter
from collections import defaultdict
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

from transformers import AutoTokenizer

from WSIatScale.create_inverted_index import full_words_tokens
from WSIatScale.analyze import npy_file_path, REPS_DIR
from WSIatScale.cluster_reps_per_token import read_clustering_data
from utils.utils import tokenizer_params, jaccard_score_between_elements

SENTS_BY_CLUSTER = 'sents_by_cluster'

TOP_REPS_TO_LOOK_ON = 10
HALF_WORDS_LIST = np.load(f"non-full-words/non-full-words-bert-large-cased-whole-word-masking.npy") #Just for BERT

def main(args):
    model_hf_path = tokenizer_params[args.dataset]
    tokenizer = AutoTokenizer.from_pretrained(model_hf_path, use_fast=True)
    replacements_dir = os.path.join(args.data_dir, REPS_DIR)
    tokens_to_index = full_words_tokens(args.dataset, tokenizer)

    files = data_files(replacements_dir)
    print(f"total {len(files)} files.")
    partial_find_and_write = partial(find_and_write, data_dir=args.data_dir, tokens_to_index=tokens_to_index, replacements_dir=replacements_dir)
    with Pool(cpu_count()) as p:
        list(tqdm(p.imap(partial_find_and_write, files), total=len(files)))

def find_and_write(filename, data_dir, tokens_to_index, replacements_dir):
    tokens_to_clusters = find_clusters(os.path.join(replacements_dir, filename), data_dir, tokens_to_index)
    write_clusters(data_dir, filename, tokens_to_clusters)

def data_files(replacements_dir):
    files = set()
    for file in os.listdir(replacements_dir):
        splits = file.split('-')
        files.add(f"{splits[0]}-{splits[1]}")
    
    return files

def find_clusters(filename, data_dir, tokens_to_index):
    tokens_to_clusters = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    all_tokens = np.load(npy_file_path(data_dir, filename, 'tokens'), mmap_mode='r')
    all_reps = np.load(npy_file_path(data_dir, filename, 'reps'), mmap_mode='r')
    for pos, (token, token_reps) in enumerate(zip(all_tokens, all_reps)):
        if token in tokens_to_index and bert_full_word_validator(all_tokens, pos):
            top_token_reps = token_reps[:TOP_REPS_TO_LOOK_ON]
            clustering_data = read_clustering_data(data_dir, token)
            for method in clustering_data.keys():
                for n_reps in clustering_data[method]:
                    token_precomputed_clusters = clustering_data[method][n_reps]
                    jaccard_scores = []
                    for pre_computed_cluster in token_precomputed_clusters:
                        pre_computed_cluster_set = set([d[0] for d in pre_computed_cluster])
                        similarity = jaccard_score_between_elements(pre_computed_cluster_set, top_token_reps)
                        jaccard_scores.append(similarity)

                    if len(jaccard_scores) > 0:
                        cluster_id, best_jaccard_score = max(enumerate(jaccard_scores), key=itemgetter(1))
                        tokens_to_clusters[token][method][n_reps][cluster_id].append((pos, best_jaccard_score))

    return tokens_to_clusters

def write_clusters(data_dir, reps_file, tokens_to_clusters):
    for token in tokens_to_clusters:
        for method in tokens_to_clusters[token]:
            for n_reps in tokens_to_clusters[token][method]:
                for cluster_id in tokens_to_clusters[token][method][n_reps]:
                    positions_and_confidence = tokens_to_clusters[token][method][n_reps][cluster_id]
                    token_cluster_file = os.path.join(data_dir, SENTS_BY_CLUSTER, f"{token}-{method}-{n_reps}.{cluster_id}")
                    with open(token_cluster_file, 'a+') as f:
                        stringed_positions_and_confidence = ' '.join([f"{p},{round(c, 2)}" for p, c in positions_and_confidence])
                        f.write(f"{reps_file}\t{stringed_positions_and_confidence}\n")

def bert_full_word_validator(tokens, pos):
    if pos + 1 == len(tokens):
        return True
    if tokens[pos + 1] in HALF_WORDS_LIST:
        return False
    return True
    # 'Wikipedia-RoBERTa'
    #     raise NotImplementedError


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--data_dir", type=str, default="replacements")
    parser.add_argument("--dataset", type=str, choices=['CORD-19', 'Wikipedia-roberta', 'Wikipedia-BERT'])
    args = parser.parse_args()

    outdir = os.path.join(args.data_dir, SENTS_BY_CLUSTER)
    assert len(os.listdir(outdir)) == 0, f"Sents by cluster already available, should delete first {outdir}"

    main(args)