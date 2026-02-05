@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 请先在 GitHub 新建空仓库: https://github.com/new
echo 仓库名建议: camera_ocr_llm，不要勾选 Add README
echo.
set GITHUB_USER=freshmanc
set /p GITHUB_USER=请输入你的 GitHub 用户名 [默认 freshmanc]: 
if "%GITHUB_USER%"=="" set GITHUB_USER=freshmanc
echo.
echo 添加远程并推送到 origin main ...
git remote remove origin 2>nul
git remote add origin https://github.com/%GITHUB_USER%/camera_ocr_llm.git
git branch -M main
git push -u origin main
if errorlevel 1 (
  echo.
  echo 若推送失败：请确认 1^) 已在 GitHub 建好同名仓库 2^) 已登录 GitHub ^(浏览器或 token^)
  echo 使用 token 时可将上面 URL 改为: https://你的token@github.com/%GITHUB_USER%/camera_ocr_llm.git
)
echo.
pause
