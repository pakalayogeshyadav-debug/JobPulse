try:
    with open("final_verification.md", encoding="utf-8") as f:
        print(f.read(3000))
except Exception:
    print("UTF-8 failed, trying utf-16")
    with open("final_verification.md", encoding="utf-16") as f:
        print(f.read(3000))
