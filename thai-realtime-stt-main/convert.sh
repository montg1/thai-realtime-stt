set -e
pip install -q "transformers==4.44.2" 2>&1 | tail -2
python3 -c "import torch,transformers; print('torch', torch.__version__, '| transformers', transformers.__version__)"
M=nectec/Pathumma-whisper-th-large-v3
OUT=/out/Pathumma-whisper-th-large-v3-ct2-fp16
rm -rf "$OUT"
echo ">>> converting $M -> CT2 float16"
ct2-transformers-converter --model "$M" --output_dir "$OUT" \
  --quantization float16 --copy_files preprocessor_config.json tokenizer_config.json \
  special_tokens_map.json added_tokens.json vocab.json merges.txt normalizer.json
echo ">>> exporting tokenizer.json"
python3 -c "
from transformers import WhisperTokenizerFast
t=WhisperTokenizerFast.from_pretrained('$M')
t.backend_tokenizer.save('$OUT/tokenizer.json')
print('vocab size:', t.vocab_size)
"
ls -la "$OUT"
echo ">>> CONVERSION DONE"
