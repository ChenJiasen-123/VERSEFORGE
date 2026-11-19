"""Verified user-positive fragments for an optional generation-only experiment."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_examples(root=ROOT):
    asset = (root/'poetry_agent/data/aesthetic-examples.json').read_bytes()
    config = json.loads(asset)
    comment_bytes = (root/config['user_comment_file']).read_bytes()
    if hashlib.sha256(comment_bytes).hexdigest() != config['user_comment_sha256']:
        raise ValueError('审美示例用户点评来源校验失败')
    feedback_bytes = (root/config['feedback_file']).read_bytes()
    if hashlib.sha256(feedback_bytes).hexdigest() != config['feedback_sha256']:
        raise ValueError('审美示例反馈来源校验失败')
    feedback = json.loads(feedback_bytes)
    packet_bytes = (root/feedback['source_blind_packet']).read_bytes()
    if feedback['reviewer_kind'] != 'user' or hashlib.sha256(packet_bytes).hexdigest() != feedback['source_sha256']:
        raise ValueError('审美示例作品来源校验失败')
    samples = {s['sample_id']: s['poem'] for pair in json.loads(packet_bytes) for s in pair['samples']}
    examples = []
    for observation in feedback['observations']:
        sid = observation['sample_id']
        if sid not in config['editor_observations']:
            continue
        quote = '\n'.join(observation['exact_body_quotes'])
        comment = config['user_comment_excerpts'][sid]
        if (observation['feedback_kind'] != 'explicit_positive_observation' or not quote.strip()
                or quote not in '\n'.join(samples[sid]['lines'])):
            raise ValueError('审美示例引文或反馈类型不一致')
        if not isinstance(comment, str) or not comment.strip() or comment not in comment_bytes.decode('utf-8'):
            raise ValueError('审美示例用户原话不一致')
        examples.append({'sample_id': sid, 'quote': quote,
                         'user_comment_excerpt': comment,
                         'user_feedback': '用户明确正面点评此片段；不等于配对优胜或整体质量认证',
                         'editor_observation': config['editor_observations'][sid],
                         'observation_author': 'assistant'})
    if len(examples) != len(config['editor_observations']):
        raise ValueError('审美示例缺少对应的用户反馈')
    return ({'instruction': config['instruction'], 'examples': examples},
            {'profile': config['profile'], 'sample_ids': [x['sample_id'] for x in examples],
             'asset_sha256': hashlib.sha256(asset).hexdigest(),
             'feedback_sha256': config['feedback_sha256'], 'packet_sha256': feedback['source_sha256'],
             'user_comment_sha256': config['user_comment_sha256'],
             'scope': 'generation_examples_not_parameter_training_or_quality_labels'})
