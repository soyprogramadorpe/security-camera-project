import traceback
print("Testing import face_recognition_models...")
try:
    import face_recognition_models
    print("Successfully imported face_recognition_models. Location:", face_recognition_models.__file__)
except Exception as e:
    print("Failed to import face_recognition_models:")
    traceback.print_exc()
