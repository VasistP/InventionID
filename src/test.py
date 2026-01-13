from openai import OpenAI

client = OpenAI(api_key="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")  # uses OPENAI_API_KEY env var

print("Uploading...")
f = client.files.create(
    file=open("InventionID\doc1.pdf", "rb"),
    purpose="user_data",
)
print("Uploaded file:", f.id)