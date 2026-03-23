import traceback
try:
    import face_recognition
    print("Success")
except Exception as e:
    traceback.print_exc()
