from analyzer.scanner import scan_repo


def analyze(url):
    files = scan_repo(url)
    print(files)



analyze(https://github.com/vishal-baliyan-ji/Liberary_management_system)