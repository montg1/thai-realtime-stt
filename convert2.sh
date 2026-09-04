set -e
pip install -q "transformers==4.44.2" 2>&1 | tail -1
M=biodatlab/distill-whisper-th-small
OUT=/out/distill-whisper-th-small-ct2-fp16
rm -rf "$OUT"
echo ">>> converting $M"
ct2-transformers-converter --model "$M" --output_dir "$OUT" \
  --quantization float16 --copy_files tokenizer.json preprocessor_config.json \
  tokenizer_config.json special_tokens_map.json added_tokens.json vocab.json merges.txt normalizer.json
ls -la "$OUT"
python3 -c "
import json;c=json.load(open('$OUT/config.json'));print('lang_ids:',len(c.get('lang_ids',[])))
from tokenizers import Tokenizer;print('vocab:',Tokenizer.from_file('$OUT/tokenizer.json').get_vocab_size())"
echo ">>> DONE"
