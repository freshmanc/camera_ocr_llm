# 把代码推送到 GitHub（保留历史记录）

本地已经完成：`git init`、首次提交（38 个文件）。接下来在 GitHub 上建仓库并推送即可。

## 1. 设置你的 Git 身份（建议只做一次）

在任意目录打开命令行执行（把下面改成你的名字和邮箱）：

```bash
git config --global user.email "你的邮箱@example.com"
git config --global user.name "你的名字或 GitHub 用户名"
```

## 2. 在 GitHub 上新建仓库

1. 打开 https://github.com/new
2. **Repository name** 填：`camera_ocr_llm`（或你喜欢的名字）
3. 选 **Private** 或 **Public**
4. **不要**勾选 "Add a README file"（本地已有代码）
5. 点 **Create repository**

## 3. 在项目目录里推送

在项目目录 `camera_ocr_llm` 下打开命令行，把下面 `你的用户名` 换成你的 GitHub 用户名：

```bash
cd "c:\Users\Lenovo\Desktop\testing cursor\camera_ocr_llm"

git remote add origin https://github.com/你的用户名/camera_ocr_llm.git
git branch -M main
git push -u origin main
```

若 GitHub 提示用 **SSH**，则用：

```bash
git remote add origin git@github.com:你的用户名/camera_ocr_llm.git
git branch -M main
git push -u origin main
```

推送时按提示登录 GitHub（浏览器或 token）即可。之后每次改完代码可执行：

```bash
git add .
git commit -m "简短说明"
git push
```

这样就有完整历史记录了。
