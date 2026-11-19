"""QLoRA text-revision experiment. No model loading without --train.

Sources: HF Transformers Trainer and PEFT v0.21 quantization guides.
Runtime GPU verification remains required; syntax checks are not training.
"""
import argparse
import hashlib
import json
from pathlib import Path


def load_rows(path):
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    selected = [r for r in rows if r.get('approved_for_training') is True]
    families = {}
    for row in selected:
        family, partition = row['family_id'], row['partition']
        if partition not in ('train_candidate', 'holdout_candidate'):
            raise ValueError('Invalid data partition')
        if family in families and families[family] != partition:
            raise ValueError('Same topic family crosses partitions')
        families[family] = partition
        if not row.get('approval_basis'):
            raise ValueError('Accepted records must state their review basis')
        if not row.get('revision_instruction'):
            raise ValueError('Accepted records must specify the requested revision')
    return selected


def encode_row(row, tokenizer, max_length):
    messages = [{'role': 'system', 'content': '依据题目与原稿修订诗歌，保留有效表达；只返回标题和正文的JSON。'},
                {'role': 'user', 'content': json.dumps({'topic': row['topic'], 'original': row['original'],
                    'revision_instruction': row.get('revision_instruction', '')}, ensure_ascii=False)}]
    prefix = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages + [{'role': 'assistant', 'content': json.dumps(row['revision'], ensure_ascii=False)}], tokenize=True)
    if full[:len(prefix)] != prefix or len(full) <= len(prefix):
        raise ValueError('Chat template does not expose a safe assistant boundary')
    if len(full) > max_length:
        raise ValueError('Example too long; refusing silent truncation')
    return {'input_ids': full, 'attention_mask': [1] * len(full),
            'labels': [-100] * len(prefix) + full[len(prefix):]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path(__file__).parent / 'training/candidates/revisions.jsonl')
    parser.add_argument('--train', action='store_true')
    parser.add_argument('--model', default='Qwen/Qwen3-4B-Instruct-2507')
    parser.add_argument('--model-revision', help='Pinned model repository commit')
    parser.add_argument('--output', type=Path, default=Path('training/adapter-experiment'))
    args = parser.parse_args()
    rows = load_rows(args.data)
    train = [r for r in rows if r['partition'] == 'train_candidate']
    held = [r for r in rows if r['partition'] == 'holdout_candidate']
    print(json.dumps({'accepted_train': len(train), 'accepted_holdout': len(held),
                      'training_requested': args.train, 'training_started': False}))
    if not args.train:
        return
    if not train or not held:
        raise ValueError('Accepted train and independent holdout records are required')
    if not args.model_revision or len(args.model_revision) != 40 or any(c not in '0123456789abcdef' for c in args.model_revision):
        raise ValueError('Pin an exact model commit before training')
    if args.output.exists():
        raise ValueError('Output already exists; use a new experiment directory')
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    if not torch.cuda.is_available():
        raise RuntimeError('This QLoRA experiment requires a verified CUDA device')
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.model_revision)
    tokenizer.pad_token = tokenizer.pad_token or tokenizer.eos_token
    examples = [encode_row(r, tokenizer, 2048) for r in train]
    evaluation = [encode_row(r, tokenizer, 2048) for r in held]
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                              bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=args.model_revision,
                quantization_config=quant, device_map={'': torch.cuda.current_device()})
    model = get_peft_model(prepare_model_for_kbit_training(model), LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, target_modules='all-linear', task_type='CAUSAL_LM'))
    model.config.use_cache = False
    def collate(batch):
        width = max(len(x['input_ids']) for x in batch)
        return {key: torch.tensor([x[key] + [pad] * (width - len(x[key])) for x in batch])
                for key, pad in [('input_ids', tokenizer.pad_token_id), ('attention_mask', 0), ('labels', -100)]}
    settings = TrainingArguments(output_dir=str(args.output), per_device_train_batch_size=1,
        per_device_eval_batch_size=1, gradient_accumulation_steps=8, num_train_epochs=1,
        learning_rate=1e-4, bf16=dtype == torch.bfloat16, fp16=dtype == torch.float16,
        report_to='none', save_strategy='no', seed=42)
    trainer = Trainer(model=model, args=settings, train_dataset=examples, eval_dataset=evaluation, data_collator=collate)
    trainer.train()
    metrics = trainer.evaluate()
    trainer.save_model(str(args.output))
    tokenizer.save_pretrained(args.output)
    (args.output / 'experiment.json').write_text(json.dumps({'model': args.model,
        'revision': args.model_revision, 'dataset_sha256': hashlib.sha256(args.data.read_bytes()).hexdigest(),
        'metrics': metrics, 'literary_gain_verified': False}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
